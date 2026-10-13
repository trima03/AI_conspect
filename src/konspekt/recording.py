"""Microphone recording to a streaming PCM WAV file; no network or GUI imports."""
from __future__ import annotations

import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Callable

from . import storage

MAX_SECONDS = 4 * 60 * 60
MAX_RECORDING_BYTES = 2 * 1024**3 - 44


class RecordingError(RuntimeError):
    pass


def _sounddevice():
    try:
        import sounddevice
        return sounddevice
    except (ImportError, OSError) as error:
        raise RecordingError("Нет библиотеки записи или PortAudio. Установите зависимости: python -m pip install -e '.[desktop,mac]'") from error


def list_input_devices() -> list[tuple[int, str]]:
    try:
        return [(index, item["name"]) for index, item in enumerate(_sounddevice().query_devices())
                if item["max_input_channels"] > 0]
    except RecordingError:
        raise
    except Exception as error:
        raise RecordingError(f"Не удалось получить список микрофонов: {error}") from error


def record_audio(
    stop_event: threading.Event, *, device: int | None = None,
    directory: Path | None = None, duration_seconds: float | None = None,
    progress: Callable[[float, float], None] | None = None,
) -> Path:
    """Blocking capture, intended for a worker. Stop event saves and closes WAV.

    On capture failure a partial WAV is preserved and named in the error message.
    The callback receives recorded seconds and peak level (0..1).
    """
    if duration_seconds is not None and not 0 < duration_seconds <= MAX_SECONDS:
        raise RecordingError("Длительность должна быть от 0 до 14400 секунд.")
    sd = _sounddevice()
    import numpy as np
    directory = directory or storage.get_data_dir() / "recordings"
    path = None
    frames_written = 0
    try:
        info = sd.query_devices(device, "input")
        rate = int(info["default_samplerate"])
        if rate <= 0 or info["max_input_channels"] < 1:
            raise RecordingError("У выбранного устройства нет входа для записи.")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"recording_{uuid.uuid4().hex}.wav"
        max_frames = min(int((duration_seconds or MAX_SECONDS) * rate), MAX_RECORDING_BYTES // 2)
        block = max(1, rate // 10)
        # Exclusive creation prevents accidental overwrites.
        with path.open("xb") as file, wave.open(file, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            with sd.RawInputStream(samplerate=rate, channels=1, dtype="int16", device=device) as stream:
                if progress:
                    progress(0, 0)
                idle_since = time.monotonic()
                while not stop_event.is_set() and frames_written < max_frames:
                    available = stream.read_available
                    if available <= 0:
                        if not stream.active or time.monotonic() - idle_since > 5:
                            raise RecordingError("Микрофон перестал передавать звук.")
                        stop_event.wait(0.03)
                        continue
                    data, overflowed = stream.read(min(block, available, max_frames - frames_written))
                    if overflowed:
                        raise RecordingError("Звук поступает с пропусками. Закройте тяжёлые программы и повторите запись.")
                    output.writeframes(data)
                    frames_written += len(data) // 2
                    idle_since = time.monotonic()
                    if progress:
                        samples = np.frombuffer(data, dtype=np.int16).astype(np.int32)
                        peak = float(np.max(np.abs(samples))) / 32768 if len(samples) else 0
                        progress(frames_written / rate, peak)
        if not frames_written:
            path.unlink(missing_ok=True)
            raise RecordingError("Запись остановлена до получения звука.")
        return path
    except Exception as error:
        tail = ""
        if path is not None and path.exists():
            if frames_written:
                tail = f" Часть записи сохранена: {path}"
            else:
                path.unlink(missing_ok=True)
        if isinstance(error, RecordingError):
            raise RecordingError(str(error) + tail) from error
        raise RecordingError(
            "Не удалось записать микрофон. Проверьте устройство и разрешение на микрофон "
            f"для PyCharm/Terminal в настройках macOS. {error}{tail}"
        ) from error
