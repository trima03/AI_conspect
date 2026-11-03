"""Local Whisper transcription. Audio never leaves the computer.

Model weights are downloaded from Hugging Face on first use, then cached.
MLX is used on Apple Silicon; the optional CPU backend uses faster-whisper.
"""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audio import ALLOWED_EXTENSIONS
from . import storage
import shutil

DEFAULT_MODEL = "turbo"
MAX_FILE_BYTES = 2 * 1024**3
MAX_DURATION_SECONDS = 4 * 60 * 60
SAMPLE_RATE = 16000
CHUNK_SECONDS = 120
# Mild reduction of steady noise; overlapping voices still need a closer microphone.
CLASSROOM_FILTER = "highpass=f=80,lowpass=f=7600,afftdn=nr=10:nf=-45:tn=1"
MLX_MODELS = {"turbo": "mlx-community/whisper-large-v3-turbo-4bit", "tiny": "mlx-community/whisper-tiny", "small": "mlx-community/whisper-small-mlx"}
from .compute import MODEL_LOCK as _MODEL_LOCK
_CPU_MODELS = {}


class TranscriptionError(RuntimeError):
    """An actionable error suitable for display."""


class TranscriptionCancelled(TranscriptionError):
    pass


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    model: str
    languages: tuple[str, ...] = ()
    segments: tuple[TranscriptSegment, ...] = ()


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise TranscriptionCancelled("Распознавание отменено. Аудиозапись сохранена.")


def _decode_audio(path: Path, destination: Path, cancel_event, timeout_seconds: int,
                  *, reduce_noise: bool = False) -> None:
    try:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as error:
        raise TranscriptionError("Не найден FFmpeg. Выполните: python -m pip install -e .") from error
    # Write PCM to disk, rather than keeping an entire lesson in memory.
    cmd = [executable, "-nostdin", "-v", "error", "-y", "-i", str(path),
           "-t", str(MAX_DURATION_SECONDS + 1), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE)]
    if reduce_noise:
        cmd.extend(["-af", CLASSROOM_FILTER])
    cmd.extend(["-c:a", "pcm_s16le", str(destination)])
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errors) as process:
            deadline = time.monotonic() + timeout_seconds
            try:
                while process.poll() is None:
                    _check_cancel(cancel_event)
                    if time.monotonic() > deadline:
                        raise TranscriptionError("Подготовка аудио заняла слишком много времени.")
                    time.sleep(0.1)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if process.returncode:
                raise TranscriptionError("Не удалось прочитать аудио. Проверьте, что запись воспроизводится и не повреждена.")


def _mlx_model_path(model: str) -> str:
    if model != "turbo":
        return MLX_MODELS[model]
    from huggingface_hub import snapshot_download
    snapshot = Path(snapshot_download(MLX_MODELS[model], allow_patterns=["config.json", "model.safetensors"]))
    # The compact model uses model.safetensors; mlx-whisper 0.4 expects
    # weights.safetensors. Adapt filenames without copying or altering weights.
    adapter = storage.get_data_dir() / "models" / "whisper-turbo" / snapshot.name
    adapter.mkdir(parents=True, exist_ok=True)
    config = adapter / "config.json"
    if not config.is_file():
        shutil.copyfile(snapshot / "config.json", config)
    weights = adapter / "weights.safetensors"
    if not weights.exists():
        weights.symlink_to((snapshot / "model.safetensors").resolve())
    return str(adapter)


def _chunk_cut(samples, is_final: bool) -> int:
    """Prefer a quiet 100 ms interval near the boundary over cutting a word."""
    import numpy as np
    if is_final or len(samples) < 10 * SAMPLE_RATE:
        return len(samples)
    window = SAMPLE_RATE // 10
    search = min(len(samples), 3 * SAMPLE_RATE)
    start = len(samples) - search
    tail = samples[start: start + search // window * window].reshape(-1, window)
    energy = np.sqrt(np.mean(tail ** 2, axis=1))
    best = int(np.argmin(energy))
    return start + best * window + window // 2 if energy[best] < .003 else len(samples)


def _recognize(samples, *, backend, model, language, prompt):
    if backend == "mlx":
        import mlx_whisper
        return mlx_whisper.transcribe(
            samples, path_or_hf_repo=_mlx_model_path(model), language=language,
            initial_prompt=prompt, verbose=None, condition_on_previous_text=False,
            temperature=0.0, no_speech_threshold=0.5, logprob_threshold=-0.8,
        )
    from faster_whisper import WhisperModel
    if model not in _CPU_MODELS:
        _CPU_MODELS[model] = WhisperModel("large-v3-turbo" if model == "turbo" else model, device="cpu", compute_type="int8")
    segments, info = _CPU_MODELS[model].transcribe(
        samples, language=language, initial_prompt=prompt,
        vad_filter=True, condition_on_previous_text=False, beam_size=5, temperature=0.0,
    )
    parts = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
    return {"text": " ".join(s["text"].strip() for s in parts), "segments": parts, "language": info.language}


def transcribe_audio(
    audio_path: str | Path, *, language: str = "ru", prompt: str | None = None,
    model: str | None = None, backend: str = "auto", timeout_seconds: int = 300,
    cancel_event: threading.Event | None = None,
    progress: Callable[[str], None] | None = None,
    reduce_noise: bool = False,
) -> TranscriptionResult:
    """Transcribe in bounded chunks, without an API key or paid service.

    Cancellation is checked during decoding and between model calls. An ongoing
    download/model call must finish first. timeout_seconds bounds decoding only.
    Call from a worker thread, never from the GUI thread.
    """
    report = progress or (lambda message: None)
    _check_cancel(cancel_event)
    path = Path(audio_path).expanduser().resolve()
    model = model or os.environ.get("KONSPEKT_WHISPER_MODEL", DEFAULT_MODEL)
    if model not in MLX_MODELS:
        raise TranscriptionError("Доступные модели: turbo, small, tiny.")
    if backend == "auto":
        backend = "mlx" if platform.system() == "Darwin" and platform.machine() == "arm64" else "cpu"
    if backend not in ("mlx", "cpu"):
        raise TranscriptionError("Доступные движки: auto, mlx, cpu.")
    if not path.is_file():
        raise TranscriptionError(f"Аудиофайл не найден: {path}")
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise TranscriptionError("Неподдерживаемый формат аудио: " + path.suffix)
    if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise TranscriptionError("Аудиофайл должен быть непустым и не больше 2 ГБ.")
    if timeout_seconds <= 0:
        raise TranscriptionError("Время ожидания должно быть положительным.")
    if not isinstance(reduce_noise, bool):
        raise TranscriptionError("Режим снижения шума должен быть включён или выключен.")
    try:
        import numpy as np
        report("Снижение фонового шума во временной копии записи…" if reduce_noise else "Подготовка аудиозаписи…")
        with tempfile.TemporaryDirectory(prefix="konspekt-audio-") as temp:
            decoded = Path(temp) / "audio.wav"
            _decode_audio(path, decoded, cancel_event, timeout_seconds, reduce_noise=reduce_noise)
            with wave.open(str(decoded), "rb") as audio:
                frames = audio.getnframes()
                if not frames:
                    raise TranscriptionError("В файле нет аудиоданных.")
                if frames / SAMPLE_RATE > MAX_DURATION_SECONDS:
                    raise TranscriptionError("Максимальная длительность записи — 4 часа.")
                _check_cancel(cancel_event)
                report("Загрузка модели. При первом запуске нужны интернет и время для скачивания…")
                # MLX caches a single model globally; serialize calls across threads.
                while not _MODEL_LOCK.acquire(timeout=0.2):
                    _check_cancel(cancel_event)
                try:
                    all_segments = []
                    texts = []
                    chunk_frames = CHUNK_SECONDS * SAMPLE_RATE
                    position = 0
                    index = 0
                    while position < frames:
                        _check_cancel(cancel_event)
                        audio.setpos(position)
                        samples = np.frombuffer(audio.readframes(chunk_frames), dtype="<i2").astype(np.float32) / 32768.0
                        cut = _chunk_cut(samples, position + len(samples) >= frames)
                        samples = samples[:cut]
                        offset = position / SAMPLE_RATE
                        position += cut
                        index += 1
                        report(f"Распознавание: {round(position * 100 / frames)}%, фрагмент {index}…" + (" При первом запуске ожидайте скачивания модели." if index == 1 else ""))
                        # Skip genuine silence, including very low-level background noise.
                        if float(np.sqrt(np.mean(samples ** 2))) < .0001:
                            continue
                        context = prompt or ""
                        if texts:
                            context = (context + "\n" + texts[-1][-200:]).strip()
                        payload = _recognize(samples, backend=backend, model=model, language=language, prompt=context or None)
                        _check_cancel(cancel_event)
                        text = payload.get("text", "").strip()
                        if text:
                            texts.append(text)
                        for item in payload.get("segments", []):
                            all_segments.append(TranscriptSegment(
                                offset + float(item["start"]), offset + float(item["end"]), item["text"].strip()))
                finally:
                    _MODEL_LOCK.release()
        if not texts:
            raise TranscriptionError("Речь не обнаружена. Проверьте громкость записи и выбранный микрофон.")
        report("Расшифровка готова.")
        return TranscriptionResult("\n\n".join(texts), model, (language,), tuple(all_segments))
    except TranscriptionError:
        raise
    except ImportError as error:
        if "metal" in str(error).lower():
            raise TranscriptionError("MLX не получил доступ к графике Mac. Запустите приложение из PyCharm или Terminal; для CPU установите .[cpu] и выберите --backend cpu.") from error
        extra = "mac" if backend == "mlx" else "cpu"
        raise TranscriptionError(f'Не установлены зависимости распознавания. Выполните: python -m pip install -e ".[desktop,{extra}]"') from error
    except Exception as error:
        raise TranscriptionError(f"Не удалось распознать запись локально: {error}") from error
