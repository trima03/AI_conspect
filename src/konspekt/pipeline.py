"""Connect local transcription to the lessons created by the desktop app."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from . import storage
from .transcription import TranscriptionCancelled, TranscriptionError, transcribe_audio

logger = logging.getLogger(__name__)


def transcribe_lesson(
    lesson_id: int, *, model: str = "small", backend: str = "auto",
    language: str = "ru", prompt: str | None = None,
    cancel_event: threading.Event | None = None, progress: Callable[[str], None] | None = None,
) -> storage.Lesson:
    lesson = storage.claim_lesson_for_transcription(lesson_id)
    try:
        result = transcribe_audio(lesson.audio_path, model=model, backend=backend,
                                  language=language, prompt=prompt,
                                  cancel_event=cancel_event, progress=progress)
        if cancel_event is not None and cancel_event.is_set():
            raise TranscriptionCancelled("Распознавание отменено. Аудиозапись сохранена.")
        return storage.save_lesson_transcript(lesson_id, result.text)
    except BaseException as error:
        try:
            if isinstance(error, (TranscriptionCancelled, KeyboardInterrupt)):
                storage.set_lesson_status(lesson_id, storage.STATUS_QUEUED)
            else:
                storage.set_lesson_status(lesson_id, storage.STATUS_FAILED, str(error))
        except Exception:
            logger.exception("Не удалось записать статус ошибки урока %s", lesson_id)
        raise
