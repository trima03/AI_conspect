"""Хранилище данных AIKonspekt: предметы и уроки в базе SQLite.

Как пользоваться:
    1. При старте приложения один раз вызови init_db().
    2. Дальше используй create_subject, create_lesson, set_lesson_status и т.д.

Используются только встроенные модули Python (sqlite3 и другие).
Код совместим с Python 3.10 и новее.
"""

from __future__ import annotations

import os
import hashlib
import uuid
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# --- Статусы обработки урока ---------------------------------------------

STATUS_QUEUED = "queued"          # ждёт обработки
STATUS_PROCESSING = "processing"  # обрабатывается
STATUS_COMPLETED = "completed"    # готово
STATUS_FAILED = "failed"          # ошибка

ALL_STATUSES = (STATUS_QUEUED, STATUS_PROCESSING, STATUS_COMPLETED, STATUS_FAILED)

# --- Расположение данных -------------------------------------------------

# Если задана эта переменная окружения, данные хранятся в указанной папке.
# Нужна для проверок (check_storage.py), чтобы не трогать настоящую базу.
DATA_DIR_ENV_VAR = "KONSPEKT_DATA_DIR"


def get_data_dir() -> Path:
    """Папка с данными: <корень проекта>/data (или папка из KONSPEKT_DATA_DIR)."""
    custom = os.environ.get(DATA_DIR_ENV_VAR)
    if custom:
        return Path(custom).expanduser().resolve()

    # Этот файл лежит в <корень>/src/konspekt/storage.py,
    # поэтому корень проекта на две папки выше.
    project_root = Path(__file__).resolve().parents[2]
    if (project_root / "pyproject.toml").is_file():
        return project_root / "data"

    # Запасной вариант: пакет установлен не "по ссылке", корень найти нельзя.
    return Path.cwd() / "data"


def get_db_path() -> Path:
    """Путь к файлу базы данных."""
    return get_data_dir() / "konspekt.db"


def get_audio_dir() -> Path:
    """Папка для аудиофайлов (понадобится на этапе 2)."""
    return get_data_dir() / "audio"


# --- Ошибки --------------------------------------------------------------


class StorageError(Exception):
    """Базовая ошибка хранилища."""


class DuplicateSubjectError(StorageError):
    """Предмет с таким названием уже существует."""


class NotFoundError(StorageError):
    """Запись (предмет или урок) не найдена."""


# --- Структуры записей ---------------------------------------------------


@dataclass(frozen=True)
class Subject:
    id: int
    name: str
    created_at: str


@dataclass(frozen=True)
class Lesson:
    id: int
    subject_id: int
    title: str
    audio_path: str
    status: str
    transcript: str | None
    summary: str | None
    error_message: str | None
    created_at: str
    updated_at: str


# --- Схема базы ----------------------------------------------------------

_STATUS_LIST_SQL = ", ".join(f"'{s}'" for s in ALL_STATUSES)

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS subjects (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    name_key   TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lessons (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id    INTEGER NOT NULL
                  REFERENCES subjects(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    audio_path    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT '{STATUS_QUEUED}'
                  CHECK (status IN ({_STATUS_LIST_SQL})),
    transcript    TEXT,
    summary       TEXT,
    error_message TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    deleted_at    TEXT,
    recording_path TEXT
);
"""

# --- Внутренние помощники ------------------------------------------------


@contextmanager
def _connect(must_exist: bool = True) -> Iterator[sqlite3.Connection]:
    """Открывает базу, сохраняет изменения при успехе, откатывает при ошибке."""
    db_path = get_db_path()
    if must_exist and not db_path.is_file():
        raise StorageError(
            "База данных ещё не создана. Сначала вызови init_db()."
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # В SQLite связи между таблицами по умолчанию выключены, включаем их.
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    """Текущее время (UTC) в виде текста, например 2026-10-09T08:30:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value: str, what: str) -> str:
    """Убирает пробелы по краям и проверяет, что текст не пустой."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} не может быть пустым.")
    return value.strip()


def _to_subject(row: sqlite3.Row) -> Subject:
    return Subject(id=row["id"], name=row["name"], created_at=row["created_at"])


def _to_lesson(row: sqlite3.Row) -> Lesson:
    # Названия колонок в таблице совпадают с полями Lesson.
    return Lesson(**{field.name: row[field.name] for field in fields(Lesson)})


# --- Создание базы -------------------------------------------------------


def init_db() -> None:
    """Создаёт папки data/ и data/audio/ и таблицы. Можно вызывать много раз."""
    get_data_dir().mkdir(parents=True, exist_ok=True)
    get_audio_dir().mkdir(parents=True, exist_ok=True)
    with _connect(must_exist=False) as conn:
        conn.executescript(_SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(lessons)")}
        for name in ("deleted_at", "recording_path"):
            if name not in columns:
                conn.execute(f"ALTER TABLE lessons ADD COLUMN {name} TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS notes_state (
            lesson_id INTEGER PRIMARY KEY REFERENCES lessons(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            source_hash TEXT NOT NULL DEFAULT '',
            model TEXT,
            job_id TEXT,
            error_message TEXT,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS trash (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            lesson_id INTEGER,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")


# --- Предметы ------------------------------------------------------------


def create_subject(name: str) -> Subject:
    """Создаёт предмет.

    Названия уникальны без учёта регистра и пробелов по краям:
    "Физика", " физика " и "ФИЗИКА" считаются одним предметом.
    """
    cleaned = _clean_text(name, "Название предмета")
    # Сравниваем по casefold(): он правильно работает и с русскими буквами
    # (встроенное сравнение SQLite без учёта регистра знает только латиницу).
    key = cleaned.casefold()

    with _connect() as conn:
        try:
            cursor = conn.execute(
                "INSERT INTO subjects (name, name_key, created_at) VALUES (?, ?, ?)",
                (cleaned, key, _now()),
            )
        except sqlite3.IntegrityError:
            raise DuplicateSubjectError(
                f"Предмет «{cleaned}» уже существует."
            ) from None
        row = conn.execute(
            "SELECT * FROM subjects WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _to_subject(row)


def rename_subject(subject_id: int, name: str) -> None:
    cleaned = _clean_text(name, "Название предмета")
    with _connect() as conn:
        try:
            updated = conn.execute(
                "UPDATE subjects SET name = ?, name_key = ? WHERE id = ?",
                (cleaned, cleaned.casefold(), subject_id),
            )
        except sqlite3.IntegrityError:
            raise DuplicateSubjectError(f"Предмет «{cleaned}» уже существует.") from None
        if not updated.rowcount:
            raise NotFoundError(f"Предмет с номером {subject_id} не найден.")


def list_subjects() -> list[Subject]:
    """Все предметы в порядке создания."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM subjects ORDER BY id").fetchall()
    return [_to_subject(row) for row in rows]


def get_subject(subject_id: int) -> Subject:
    """Предмет по номеру. Если нет такого, выдаёт NotFoundError."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"Предмет с номером {subject_id} не найден.")
    return _to_subject(row)


# --- Уроки ---------------------------------------------------------------


def create_lesson(subject_id: int, title: str, audio_path: str | Path | None, *, recording_path: str | None = None,
                  transcript: str | None = None) -> Lesson:
    """Создаёт урок из аудио или готовой расшифровки."""
    cleaned_title = _clean_text(title, "Название урока")
    text = _clean_text(transcript, "Расшифровка") if transcript is not None else None
    if audio_path is None and text is None:
        raise StorageError("Выберите аудио или добавьте расшифровку.")
    cleaned_path = _clean_text(str(audio_path), "Путь к аудиофайлу") if audio_path is not None else ""

    with _connect() as conn:
        subject = conn.execute(
            "SELECT id FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if subject is None:
            raise NotFoundError(f"Предмет с номером {subject_id} не найден.")

        now = _now()
        cursor = conn.execute(
            "INSERT INTO lessons (subject_id, title, audio_path, status, "
            "created_at, updated_at, recording_path, transcript) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (subject_id, cleaned_title, cleaned_path, STATUS_COMPLETED if text else STATUS_QUEUED,
             now, now, recording_path, text),
        )
        row = conn.execute(
            "SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL", (cursor.lastrowid,)
        ).fetchone()
    return _to_lesson(row)


def list_lessons(subject_id: int) -> list[Lesson]:
    """Все уроки предмета в порядке создания."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lessons WHERE subject_id = ? AND deleted_at IS NULL ORDER BY id", (subject_id,)
        ).fetchall()
    return [_to_lesson(row) for row in rows]


def get_lesson(lesson_id: int) -> Lesson:
    """Урок по номеру. Если нет такого, выдаёт NotFoundError."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL", (lesson_id,)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"Урок с номером {lesson_id} не найден.")
    return _to_lesson(row)


def set_lesson_status(
    lesson_id: int, status: str, error_message: str | None = None
) -> Lesson:
    """Меняет статус урока и возвращает обновлённый урок.

    Текст ошибки сохраняется только для статуса failed. При любом другом
    статусе старая ошибка стирается (например, при повторной обработке).
    """
    if status not in ALL_STATUSES:
        raise ValueError(
            f"Неизвестный статус «{status}». Допустимы: {', '.join(ALL_STATUSES)}."
        )
    if status != STATUS_FAILED:
        error_message = None

    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE lessons SET status = ?, error_message = ?, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (status, error_message, _now(), lesson_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Урок с номером {lesson_id} не найден.")
        if status != STATUS_PROCESSING:
            conn.execute("UPDATE notes_state SET status = 'cancelled', job_id = NULL, error_message = 'Обработка сброшена.', updated_at = ? WHERE lesson_id = ? AND status = 'processing'", (_now(), lesson_id))
        row = conn.execute(
            "SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL", (lesson_id,)
        ).fetchone()
    return _to_lesson(row)


def set_lesson_audio_path(lesson_id: int, audio_path: str | Path, *, recording_path: str | None = None) -> Lesson:
    """Меняет путь к аудиофайлу урока и возвращает обновлённый урок.

    Меняются только audio_path и updated_at. Остальные поля урока
    (статус, текст, конспект, ошибка) остаются как были.
    Сам аудиофайл эта функция не создаёт и не удаляет.
    """
    cleaned_path = _clean_text(str(audio_path), "Путь к аудиофайлу")

    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE lessons SET audio_path = ?, recording_path = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (cleaned_path, recording_path, _now(), lesson_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Урок с номером {lesson_id} не найден.")
        row = conn.execute(
            "SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL", (lesson_id,)
        ).fetchone()
    return _to_lesson(row)

def claim_lesson_for_transcription(lesson_id: int) -> Lesson:
    """Atomically claim work, so two workers cannot transcribe the same lesson."""
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE lessons SET status = ?, error_message = NULL, updated_at = ? "
            "WHERE id = ? AND deleted_at IS NULL AND status != ?",
            (STATUS_PROCESSING, _now(), lesson_id, STATUS_PROCESSING),
        )
        if cursor.rowcount == 0:
            if conn.execute("SELECT id FROM lessons WHERE id = ? AND deleted_at IS NULL", (lesson_id,)).fetchone() is None:
                raise NotFoundError(f"Урок с номером {lesson_id} не найден.")
            raise StorageError("Этот урок уже обрабатывается.")
        row = conn.execute("SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL", (lesson_id,)).fetchone()
    return _to_lesson(row)


def save_lesson_transcript(lesson_id: int, transcript: str) -> Lesson:
    """Save complete text and completed status in one transaction.

    A summary based on a different transcript becomes stale and is cleared.
    On failures/cancellation the processing pipeline keeps the old transcript.
    """
    text = _clean_text(transcript, "Расшифровка")
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE lessons SET summary = CASE WHEN transcript = ? THEN summary ELSE NULL END, "
            "transcript = ?, status = CASE WHEN transcript = ? AND status = ? "
            "AND EXISTS (SELECT 1 FROM notes_state WHERE lesson_id = lessons.id AND status = 'processing') "
            "THEN status ELSE ? END, "
            "error_message = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (text, text, text, STATUS_PROCESSING, STATUS_COMPLETED, _now(), lesson_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"Урок с номером {lesson_id} не найден.")
        conn.execute("UPDATE notes_state SET status = 'stale', model = NULL, job_id = NULL, error_message = NULL, updated_at = ? WHERE lesson_id = ? AND source_hash != ?", (_now(), lesson_id, transcript_hash(text)))
        row = conn.execute("SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL", (lesson_id,)).fetchone()
    return _to_lesson(row)


def update_lesson_details(lesson_id: int, subject_id: int, title: str) -> Lesson:
    cleaned = _clean_text(title, "Название лекции")
    with _connect() as conn:
        if conn.execute("SELECT id FROM subjects WHERE id = ?", (subject_id,)).fetchone() is None:
            raise NotFoundError("Предмет не найден.")
        cursor = conn.execute("UPDATE lessons SET subject_id = ?, title = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL AND status != ?", (subject_id, cleaned, _now(), lesson_id, STATUS_PROCESSING))
        if not cursor.rowcount:
            raise StorageError("Лекция не найдена или сейчас обрабатывается.")
        row = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    return _to_lesson(row)


@dataclass(frozen=True)
class NotesState:
    status: str = 'idle'
    source_hash: str = ''
    model: str | None = None
    error_message: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class NotesClaim:
    lesson: Lesson
    job_id: str


def transcript_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def get_notes_state(lesson_id: int) -> NotesState:
    get_lesson(lesson_id)
    with _connect() as conn:
        row = conn.execute('SELECT status, source_hash, model, error_message, updated_at FROM notes_state WHERE lesson_id = ?', (lesson_id,)).fetchone()
    return NotesState(**dict(row)) if row else NotesState()


def claim_lesson_for_notes(lesson_id: int) -> NotesClaim:
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL', (lesson_id,)).fetchone()
        if row is None:
            raise NotFoundError('Лекция не найдена.')
        lesson = _to_lesson(row)
        existing_job = conn.execute("SELECT status FROM notes_state WHERE lesson_id = ?", (lesson_id,)).fetchone()
        if lesson.status == STATUS_PROCESSING or (existing_job and existing_job['status'] == 'processing'):
            raise StorageError('Лекция уже обрабатывается. Дождитесь завершения.')
        if not lesson.transcript or not lesson.transcript.strip():
            raise StorageError('Сначала сохраните расшифровку лекции.')
        job_id = uuid.uuid4().hex
        conn.execute('UPDATE lessons SET status = ?, error_message = NULL, updated_at = ? WHERE id = ?', (STATUS_PROCESSING, _now(), lesson_id))
        conn.execute("""INSERT INTO notes_state (lesson_id, status, source_hash, model, job_id, error_message, updated_at)
            VALUES (?, 'processing', ?, NULL, ?, NULL, ?)
            ON CONFLICT(lesson_id) DO UPDATE SET status='processing', source_hash=excluded.source_hash,
            job_id=excluded.job_id, error_message=NULL, updated_at=excluded.updated_at""",
            (lesson_id, transcript_hash(lesson.transcript), job_id, _now()))
    return NotesClaim(lesson, job_id)


def save_lesson_summary(lesson_id: int, markdown: str, *, source_transcript: str,
                        model: str | None = None, job_id: str | None = None) -> Lesson:
    text = _clean_text(markdown, 'Конспект')
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL', (lesson_id,)).fetchone()
        if row is None:
            raise NotFoundError('Лекция не найдена.')
        if not source_transcript.strip() or row['transcript'] != source_transcript:
            raise StorageError('Расшифровка изменилась. Создайте конспект заново по актуальному тексту.')
        state = conn.execute('SELECT * FROM notes_state WHERE lesson_id = ?', (lesson_id,)).fetchone()
        if job_id is not None:
            if state is None or state['job_id'] != job_id or state['status'] != 'processing':
                raise StorageError('Эта задача конспекта больше не активна. Её результат не сохранён.')
        elif row['status'] == STATUS_PROCESSING or (state and state['status'] == 'processing'):
            raise StorageError('Дождитесь завершения обработки лекции.')
        actual_model = model or (state['model'] if state else None)
        conn.execute('UPDATE lessons SET summary = ?, status = ?, error_message = NULL, updated_at = ? WHERE id = ?', (text, STATUS_COMPLETED, _now(), lesson_id))
        conn.execute("""INSERT INTO notes_state (lesson_id, status, source_hash, model, updated_at)
            VALUES (?, 'completed', ?, ?, ?)
            ON CONFLICT(lesson_id) DO UPDATE SET status='completed', source_hash=excluded.source_hash,
            model=excluded.model, job_id=NULL, error_message=NULL, updated_at=excluded.updated_at""",
            (lesson_id, transcript_hash(source_transcript), actual_model, _now()))
        row = conn.execute('SELECT * FROM lessons WHERE id = ?', (lesson_id,)).fetchone()
    return _to_lesson(row)


def fail_notes_job(claim: NotesClaim, message: str, *, cancelled=False) -> None:
    with _connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        cursor = conn.execute("UPDATE notes_state SET status = ?, job_id = NULL, error_message = ?, updated_at = ? WHERE lesson_id = ? AND job_id = ? AND status = 'processing'",
                              ('cancelled' if cancelled else 'failed', message, _now(), claim.lesson.id, claim.job_id))
        if cursor.rowcount:
            conn.execute('UPDATE lessons SET status = ?, error_message = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL AND status = ?',
                         (claim.lesson.status, claim.lesson.error_message, _now(), claim.lesson.id, STATUS_PROCESSING))
