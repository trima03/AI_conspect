"""Connect local transcription to the lessons created by the desktop app."""
from __future__ import annotations

import logging
import threading
from typing import Callable

from . import storage
from .transcription import TranscriptionCancelled, TranscriptionError, DEFAULT_MODEL, transcribe_audio

logger = logging.getLogger(__name__)


def transcribe_lesson(
    lesson_id: int, *, model: str = DEFAULT_MODEL, backend: str = "auto",
    language: str = "ru", prompt: str | None = None,
    cancel_event: threading.Event | None = None, progress: Callable[[str], None] | None = None,
    reduce_noise: bool = False,
) -> storage.Lesson:
    lesson = storage.claim_lesson_for_transcription(lesson_id)
    try:
        subject = storage.get_subject(lesson.subject_id)
        context = f"{subject.name}. {lesson.title}. {prompt or ''}".strip()
        result = transcribe_audio(lesson.audio_path, model=model, backend=backend,
                                  language=language, prompt=context,
                                  cancel_event=cancel_event, progress=progress, reduce_noise=reduce_noise)
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


def summarize_lesson(lesson_id: int, *, style='detailed', cancel_event=None, progress=None) -> storage.Lesson:
    """Generate notes against a snapshot; keep old notes on failure/cancellation."""
    from .notes import generate_notes, NotesCancelled
    claim = storage.claim_lesson_for_notes(lesson_id)
    try:
        subject = storage.get_subject(claim.lesson.subject_id)
        result = generate_notes(claim.lesson.transcript, title=claim.lesson.title, subject=subject.name,
                                style=style, cancel_event=cancel_event, progress=progress)
        if cancel_event is not None and cancel_event.is_set():
            raise NotesCancelled('Создание конспекта отменено.')
        return storage.save_lesson_summary(lesson_id, result.markdown,
                                          source_transcript=claim.lesson.transcript,
                                          model=result.model, job_id=claim.job_id)
    except BaseException as error:
        try:
            storage.fail_notes_job(claim, str(error), cancelled=isinstance(error, (NotesCancelled, KeyboardInterrupt)))
        except Exception:
            logger.exception('Не удалось сохранить статус создания конспекта %s', lesson_id)
        raise
