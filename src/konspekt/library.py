"""Reversible deletion of lessons and app-owned audio; originals outside data stay intact."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import storage


@dataclass(frozen=True)
class TrashItem:
    id: int
    kind: str
    title: str
    created_at: str


@dataclass(frozen=True)
class Recording:
    path: Path
    lesson_ids: tuple[int, ...]
    size: int


def _roots():
    base = storage.get_data_dir().resolve()
    return base / "audio", base / "recordings"


def _managed(path: Path) -> bool:
    # Never follow a symlink to delete or overwrite a user's external file.
    return (not path.is_symlink() and path.absolute().parent in _roots()
            and path.resolve().parent in _roots())


def _trash_root() -> Path:
    path = storage.get_data_dir().resolve() / "trash"
    if path.is_symlink():
        raise storage.StorageError("Папка корзины не должна быть символической ссылкой.")
    return path


def _source_for(row) -> str | None:
    if row['recording_path']:
        return row['recording_path']
    # Existing lessons from the older version have no source path. The copied
    # file retains the source stem; confirm identical bytes before linking it.
    path = Path(row['audio_path'])
    if not path.is_file() or not _managed(path):
        return None
    recordings = _roots()[1]
    for original in recordings.glob('recording_*.wav'):
        if not _managed(original) or not path.stem.startswith(original.stem[:40] + '_'):
            continue
        if original.stat().st_size == path.stat().st_size:
            def digest(file):
                h = hashlib.sha256()
                with file.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(block)
                return h.digest()
            if digest(path) == digest(original):
                return str(original)
    return None


def _references(conn, excluded=None):
    result = {}
    for row in conn.execute('SELECT * FROM lessons WHERE deleted_at IS NULL'):
        if row['id'] == excluded:
            continue
        for raw in (row['audio_path'], _source_for(row)):
            if raw:
                result.setdefault(Path(raw).resolve(), []).append(row['id'])
    return result


def list_recordings() -> list[Recording]:
    with storage._connect() as conn:
        references = _references(conn)
    folder = _roots()[1]
    if not folder.is_dir() or folder.is_symlink():
        return []
    return [Recording(path, tuple(sorted(set(references.get(path.resolve(), [])))), path.stat().st_size)
            for path in sorted(folder.glob('*.wav'), key=lambda p: p.stat().st_mtime, reverse=True)
            if _managed(path)]


def list_trash() -> list[TrashItem]:
    with storage._connect() as conn:
        rows = conn.execute('SELECT id, kind, title, created_at FROM trash ORDER BY id DESC').fetchall()
    return [TrashItem(**dict(row)) for row in rows]


def _undo_moves(moves):
    for original, archived in reversed(moves):
        if archived.exists():
            if original.exists():
                raise storage.StorageError(f"Не удалось откатить перемещение: {original} уже существует. Сохранённая копия: {archived}")
            archived.rename(original)


def _move_files(paths, references, moves):
    folder = _trash_root() / uuid.uuid4().hex
    for raw in dict.fromkeys(raw for raw in paths if raw):
        path = Path(raw).absolute()
        if not _managed(path) or not path.is_file() or path.resolve() in references:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        archived = folder / f'{len(moves)}_{path.name}'
        path.rename(archived)
        moves.append((path, archived))


def archive_lesson(lesson_id: int, *, audio_only: bool = False) -> int:
    """Move a lesson or its managed audio to the app's restorable trash."""
    moves = []
    try:
        with storage._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM lessons WHERE id = ? AND deleted_at IS NULL', (lesson_id,)).fetchone()
            if row is None:
                raise storage.NotFoundError("Лекция не найдена.")
            if row['status'] == storage.STATUS_PROCESSING:
                raise storage.StorageError("Сначала завершите или отмените распознавание этой лекции.")
            if audio_only and not row['audio_path']:
                raise storage.StorageError("У лекции уже нет аудиозаписи.")
            source = _source_for(row)
            expected = [str(Path(raw).absolute()) for raw in (row['audio_path'], source)
                        if raw and _managed(Path(raw).absolute()) and Path(raw).is_file()]
            _move_files((row['audio_path'], source), _references(conn, excluded=lesson_id), moves)
            payload = {'audio_path': row['audio_path'], 'recording_path': source, 'expected': expected,
                       'moves': [(str(a), str(b)) for a, b in moves]}
            kind = 'audio' if audio_only else 'lesson'
            cursor = conn.execute('INSERT INTO trash (kind, title, lesson_id, payload, created_at) VALUES (?, ?, ?, ?, ?)',
                                  (kind, row['title'], lesson_id, json.dumps(payload), storage._now()))
            if audio_only:
                status = storage.STATUS_COMPLETED if row['transcript'] else storage.STATUS_QUEUED
                conn.execute("UPDATE lessons SET audio_path = '', recording_path = NULL, status = ?, error_message = NULL, updated_at = ? WHERE id = ?",
                             (status, storage._now(), lesson_id))
            else:
                conn.execute('UPDATE lessons SET deleted_at = ?, updated_at = ? WHERE id = ?',
                             (storage._now(), storage._now(), lesson_id))
            result = cursor.lastrowid
        return result
    except BaseException:
        _undo_moves(moves)
        raise


def archive_recording(path: Path) -> int:
    path = Path(path).absolute()
    if path.parent != _roots()[1] or not _managed(path) or not path.is_file():
        raise storage.StorageError("Можно удалить только запись из папки записей приложения.")
    moves = []
    try:
        with storage._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            refs = _references(conn)
            if path.resolve() in refs:
                raise storage.StorageError("Запись используется лекцией. Откройте лекцию и удалите её аудио или всю лекцию.")
            _move_files((str(path),), refs, moves)
            cursor = conn.execute('INSERT INTO trash (kind, title, payload, created_at) VALUES (?, ?, ?, ?)',
                                  ('recording', path.name, json.dumps({'moves': [(str(a), str(b)) for a, b in moves]}), storage._now()))
            result = cursor.lastrowid
        return result
    except BaseException:
        _undo_moves(moves)
        raise


def restore_item(trash_id: int) -> None:
    restored = []
    try:
        with storage._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            entry = conn.execute('SELECT * FROM trash WHERE id = ?', (trash_id,)).fetchone()
            if entry is None:
                raise storage.NotFoundError("Запись в корзине не найдена.")
            payload = json.loads(entry['payload'])
            if entry['kind'] in ('lesson', 'audio'):
                row = conn.execute('SELECT * FROM lessons WHERE id = ?', (entry['lesson_id'],)).fetchone()
                if row is None:
                    raise storage.NotFoundError("Лекция больше не существует.")
                if row['status'] == storage.STATUS_PROCESSING:
                    raise storage.StorageError("Нельзя восстановить аудио во время обработки.")
                if entry['kind'] == 'audio' and row['deleted_at']:
                    raise storage.StorageError("Сначала восстановите саму лекцию из корзины.")
                if entry['kind'] == 'audio' and row['audio_path']:
                    raise storage.StorageError("У лекции уже есть новое аудио. Восстановление не будет его заменять.")
            pairs = [(Path(a), Path(b)) for a, b in payload['moves']]
            for expected in payload.get('expected', []):
                path = Path(expected)
                if not path.exists() and path not in [a for a, b in pairs]:
                    raise storage.StorageError("Аудио находится в другой записи корзины. Сначала восстановите связанную лекцию или запись.")
            for original, archived in pairs:
                if (not _managed(original) or archived.is_symlink()
                        or archived.parent.parent != _trash_root() or archived.parent.is_symlink()):
                    raise storage.StorageError("В корзине указан недопустимый путь.")
                if original.exists() or original.is_symlink():
                    raise storage.StorageError(f"Файл {original.name} уже существует. Восстановление не будет его заменять.")
                if not archived.is_file():
                    raise storage.StorageError(f"Файл {archived.name} не найден в корзине.")
            for original, archived in pairs:
                original.parent.mkdir(parents=True, exist_ok=True)
                archived.rename(original)
                restored.append((archived, original))
            if entry['kind'] == 'lesson':
                conn.execute('UPDATE lessons SET deleted_at = NULL, updated_at = ? WHERE id = ?',
                             (storage._now(), entry['lesson_id']))
            elif entry['kind'] == 'audio':
                conn.execute('UPDATE lessons SET audio_path = ?, recording_path = ?, updated_at = ? WHERE id = ?',
                             (payload['audio_path'], payload.get('recording_path'), storage._now(), entry['lesson_id']))
            conn.execute('DELETE FROM trash WHERE id = ?', (trash_id,))
    except BaseException:
        _undo_moves(restored)
        raise
