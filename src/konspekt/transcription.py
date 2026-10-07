"""Transcribe a local audio file with the OpenAI Audio Transcriptions API.

The audio file is uploaded to the configured provider when ``transcribe_audio``
is called. This module never stores the API key or audio contents on disk.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = "https://api.openai.com/v1/audio/transcriptions"
DEFAULT_MODEL = "gpt-transcribe"
MAX_FILE_BYTES = 25_000_000
SUPPORTED_EXTENSIONS = {
    ".flac",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".m4a",
    ".ogg",
    ".wav",
    ".webm",
}


class TranscriptionError(RuntimeError):
    """An actionable error returned to the application or CLI."""


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    model: str
    languages: tuple[str, ...] = ()


def transcribe_audio(
    audio_path: str | Path,
    *,
    language: str = "ru",
    prompt: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout_seconds: int = 300,
) -> TranscriptionResult:
    """Upload an audio file and return its transcript.

    Args:
        audio_path: Local path to a supported audio file.
        language: Expected language as an ISO-639-1 code (``ru`` by default).
        prompt: Optional short context such as course-specific terminology.
        model: API model ID. Defaults to ``OPENAI_TRANSCRIPTION_MODEL`` or
            ``gpt-transcribe``.
        api_key: Optional key override; normally read from ``OPENAI_API_KEY``.
        timeout_seconds: Maximum time to wait for the provider response.

    Raises:
        TranscriptionError: If the file, credentials, connection, or API response
            is invalid.
    """

    path = Path(audio_path).expanduser()
    if not path.exists() or not path.is_file():
        raise TranscriptionError(f"Аудиофайл не найден: {path}")

    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise TranscriptionError(
            f"Формат {extension or '(без расширения)'} не поддерживается. "
            f"Допустимые форматы: {allowed}"
        )

    file_size = path.stat().st_size
    if file_size == 0:
        raise TranscriptionError("Аудиофайл пустой.")
    if file_size > MAX_FILE_BYTES:
        raise TranscriptionError(
            "Файл больше 25 MB. Для MVP сожмите запись или разделите её на части "
            "до 25 MB; автоматическое разбиение добавим отдельно."
        )

    resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_key:
        raise TranscriptionError(
            "Не задан OPENAI_API_KEY. Укажите его в переменных окружения; "
            "не вставляйте ключ в исходный код."
        )

    resolved_model = model or os.environ.get(
        "OPENAI_TRANSCRIPTION_MODEL", DEFAULT_MODEL
    )
    boundary = f"----AIConspect{uuid.uuid4().hex}"
    body = _make_multipart_body(
        boundary=boundary,
        path=path,
        language=language,
        prompt=prompt,
        model=resolved_model,
    )
    request = Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {resolved_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        message = _api_error_message(details) or f"HTTP {error.code}"
        if error.code == 401:
            message = "Провайдер не принял API-ключ. Проверьте OPENAI_API_KEY."
        elif error.code == 429:
            message = "Превышен лимит запросов или средств API. Попробуйте позже."
        elif error.code in (413, 400) and file_size > MAX_FILE_BYTES:
            message = "Файл превышает допустимый размер запроса."
        raise TranscriptionError(f"Ошибка сервиса распознавания: {message}") from error
    except URLError as error:
        raise TranscriptionError(
            f"Не удалось подключиться к сервису распознавания: {error.reason}"
        ) from error
    except TimeoutError as error:
        raise TranscriptionError(
            "Сервис не ответил вовремя. Повторите обработку."
        ) from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TranscriptionError(
            "Сервис вернул ответ в неизвестном формате."
        ) from error

    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise TranscriptionError("В ответе сервиса не найден распознанный текст.")

    languages = payload.get("languages", [])
    language_codes = tuple(
        item["code"]
        for item in languages
        if isinstance(item, dict) and isinstance(item.get("code"), str)
    ) if isinstance(languages, list) else ()

    return TranscriptionResult(
        text=text.strip(),
        model=resolved_model,
        languages=language_codes,
    )


def _make_multipart_body(
    *,
    boundary: str,
    path: Path,
    language: str,
    prompt: str | None,
    model: str,
) -> bytes:
    """Build a multipart request body for files capped at 25 MB."""

    marker = boundary.encode("ascii")
    pieces: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        pieces.extend(
            [
                b"--" + marker + b"\r\n",
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )

    add_field("model", model)
    add_field("response_format", "json")
    add_field("languages[]", language)
    if prompt:
        add_field("prompt", prompt)

    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    safe_filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
    pieces.extend(
        [
            b"--" + marker + b"\r\n",
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{safe_filename}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8"),
            path.read_bytes(),
            b"\r\n--" + marker + b"--\r\n",
        ]
    )
    return b"".join(pieces)


def _api_error_message(response_body: str) -> str | None:
    try:
        payload: Any = json.loads(response_body)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
    return None
