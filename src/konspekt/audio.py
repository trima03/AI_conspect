"""Безопасное сохранение аудиофайлов урока в папку data/audio/.

Что делает модуль:
    * проверяет исходный файл (существует, формат, размер);
    * копирует его в папку, которую даёт storage.get_audio_dir();
    * даёт копии безопасное уникальное имя;
    * исходный файл не изменяет и не удаляет.

Чего модуль НЕ делает: не обращается к интернету, не запускает
распознавание речи и не пишет в базу данных.

Пример:
    from konspekt import audio

    try:
        saved_path = audio.save_audio("C:/Users/me/Downloads/lesson.mp3")
    except audio.AudioError as error:
        print(error)  # понятное сообщение на русском

Код совместим с Python 3.10 и новее, сторонние библиотеки не нужны.
"""

from __future__ import annotations

import errno
import os
import re
import shutil
import uuid
from pathlib import Path

from . import storage

# --- Настройки -----------------------------------------------------------

# Форматы, которые принимает распознавание речи.
ALLOWED_EXTENSIONS = frozenset(
    {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}
)

# Максимальный размер: 25 МБ (25 * 1024 * 1024 байт).
MAX_SIZE_BYTES = 25 * 1024 * 1024

# Файл копируется кусками по 1 МБ, чтобы не читать его в память целиком.
COPY_CHUNK_SIZE = 1024 * 1024

# Сколько символов из исходного названия оставляем в имени копии.
MAX_NAME_PART_LENGTH = 40

# Сколько раз пробуем подобрать свободное имя (на практике хватает одной).
MAX_NAME_ATTEMPTS = 5

_BYTES_IN_MB = 1024 * 1024


# --- Ошибки --------------------------------------------------------------


class AudioError(Exception):
    """Общая ошибка работы с аудио. Текст ошибки можно показывать пользователю."""


class AudioFileNotFoundError(AudioError):
    """Исходный аудиофайл не найден."""


class UnsupportedAudioFormatError(AudioError):
    """Формат файла не поддерживается."""


class AudioTooLargeError(AudioError):
    """Файл больше допустимого размера."""


# --- Внутренние помощники ------------------------------------------------


def _supported_formats_text() -> str:
    return ", ".join(sorted(ext.lstrip(".") for ext in ALLOWED_EXTENSIONS))


def _format_mb(size_bytes: int) -> str:
    """Размер в мегабайтах для сообщения, например '26,3'."""
    return f"{size_bytes / _BYTES_IN_MB:.1f}".replace(".", ",")


def _too_large_error(size_bytes: int, limit: int = MAX_SIZE_BYTES) -> AudioTooLargeError:
    return AudioTooLargeError(
        f"Файл слишком большой: {_format_mb(size_bytes)} МБ. "
        f"Максимальный размер — {limit // _BYTES_IN_MB} МБ."
    )


def _make_unique_name(original_stem: str, extension: str) -> str:
    """Собирает безопасное имя вида 'урок_физики_3f9a1c0b7d2e4a68.mp3'.

    Из исходного названия остаются только буквы, цифры, '_' и '-'.
    Всё остальное (слеши, точки, двоеточия, пробелы) заменяется на '_',
    поэтому выйти за пределы папки через '../' невозможно.
    В конце всегда стоит случайный код, так что имена не повторяются.
    """
    safe_part = re.sub(r"[^\w\-]+", "_", original_stem).strip("_-")
    safe_part = safe_part[:MAX_NAME_PART_LENGTH].strip("_-")
    if not safe_part:
        safe_part = "audio"
    return f"{safe_part}_{uuid.uuid4().hex[:16]}{extension}"


def _remove_quietly(path: Path) -> None:
    """Удаляет файл, а если не получилось, молча продолжает."""
    try:
        path.unlink()
    except OSError:
        pass


def _copy_new_file(source: Path, destination: Path) -> bool:
    """Копирует файл. Возвращает False, если файл с таким именем уже есть.

    Режим "xb" не позволяет перезаписать существующий файл.
    Если копирование оборвалось, недокопированный файл удаляется.
    """
    try:
        out_file = open(destination, "xb")
    except FileExistsError:
        return False

    try:
        with out_file, open(source, "rb") as in_file:
            shutil.copyfileobj(in_file, out_file, COPY_CHUNK_SIZE)
    except BaseException:
        # К этому моменту файлы уже закрыты, поэтому удаление работает и в Windows.
        _remove_quietly(destination)
        raise
    return True


def _copy_error(source: Path, error: OSError) -> AudioError:
    """Превращает системную ошибку копирования в понятное сообщение."""
    if isinstance(error, PermissionError):
        return AudioError(
            f"Нет доступа к файлу «{source.name}». Возможно, он открыт в другой "
            "программе. Закрой её и попробуй снова."
        )
    if error.errno == errno.ENOSPC:
        return AudioError("Не хватает места на диске, чтобы сохранить аудиофайл.")
    return AudioError(f"Не удалось скопировать файл «{source.name}»: {error}")


# --- Публичные функции ---------------------------------------------------


def validate_audio_file(source_path: str | os.PathLike[str], *, max_size_bytes: int = MAX_SIZE_BYTES) -> Path:
    """Проверяет исходный файл и возвращает его путь.

    Проверяются: файл указан, существует, это файл, формат разрешён,
    файл не пустой и не больше MAX_SIZE_BYTES. Ничего не копирует.
    """
    if source_path is None or str(source_path).strip() == "":
        raise AudioError("Не указан путь к аудиофайлу.")
    try:
        source = Path(source_path).expanduser()
    except TypeError:
        raise AudioError("Путь к аудиофайлу указан неверно.") from None

    if not source.exists():
        raise AudioFileNotFoundError(f"Файл не найден: {source}")
    if not source.is_file():
        raise AudioError(
            f"Указанный путь ведёт не к файлу (возможно, это папка): {source}"
        )

    extension = source.suffix.lower()
    if not extension:
        raise UnsupportedAudioFormatError(
            f"У файла «{source.name}» нет расширения, поэтому формат неизвестен. "
            f"Допустимые форматы: {_supported_formats_text()}."
        )
    if extension not in ALLOWED_EXTENSIONS:
        raise UnsupportedAudioFormatError(
            f"Формат «{extension}» не поддерживается. "
            f"Допустимые форматы: {_supported_formats_text()}."
        )

    try:
        size = source.stat().st_size
    except OSError as error:
        raise AudioError(
            f"Не удалось прочитать файл «{source.name}»: {error}"
        ) from error
    if size == 0:
        raise AudioError(f"Файл «{source.name}» пустой (0 байт).")
    if size > max_size_bytes:
        raise _too_large_error(size, max_size_bytes)

    return source


def save_audio(source_path: str | os.PathLike[str], *, max_size_bytes: int = MAX_SIZE_BYTES) -> Path:
    """Копирует аудиофайл в папку data/audio/ и возвращает путь к копии.

    Исходный файл не меняется. Если что-то пошло не так, выдаётся AudioError
    (или одна из его разновидностей) с понятным текстом, а недокопированный
    файл удаляется.
    """
    source = validate_audio_file(source_path, max_size_bytes=max_size_bytes)
    extension = source.suffix.lower()  # в имени копии расширение всегда маленькими буквами

    audio_dir = storage.get_audio_dir()
    try:
        audio_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise AudioError(
            f"Не удалось создать папку для аудио «{audio_dir}»: {error}"
        ) from error

    destination = None
    for _ in range(MAX_NAME_ATTEMPTS):
        candidate = audio_dir / _make_unique_name(source.stem, extension)
        try:
            created = _copy_new_file(source, candidate)
        except OSError as error:
            raise _copy_error(source, error) from error
        if created:
            destination = candidate
            break
    if destination is None:
        raise AudioError(
            "Не удалось подобрать свободное имя для файла. Попробуй ещё раз."
        )

    # Контрольная проверка: копия должна быть полной и не больше лимита.
    try:
        copied_size = destination.stat().st_size
        source_size = source.stat().st_size
    except OSError as error:
        _remove_quietly(destination)
        raise AudioError(
            f"Не удалось проверить копию файла «{source.name}»: {error}"
        ) from error
    if copied_size > max_size_bytes:
        _remove_quietly(destination)
        raise _too_large_error(copied_size, max_size_bytes)
    if copied_size != source_size:
        _remove_quietly(destination)
        raise AudioError(
            f"Копия файла «{source.name}» получилась неполной. Возможно, файл "
            "менялся во время копирования. Попробуй ещё раз."
        )

    return destination
