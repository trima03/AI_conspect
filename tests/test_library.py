import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from konspekt import storage, lesson_audio, library
from konspekt.ui.overview import load_overview


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: str(self.root / 'data')})
        self.env.start()
        storage.init_db()
        self.subject = storage.create_subject('История')
        self.source = self.root / 'original.wav'
        self.source.write_bytes(b'original bytes')

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def lesson(self, source=None):
        lesson = lesson_audio.create_lesson_with_audio(self.subject.id, 'Лекция', source or self.source)
        return storage.save_lesson_transcript(lesson.id, 'Сохранённая расшифровка')

    def capture(self):
        folder = storage.get_data_dir() / 'recordings'
        folder.mkdir(exist_ok=True)
        source = folder / 'recording_abcdef1234567890abcdef1234567890ab.wav'
        source.write_bytes(b'capture original')
        return source

    def test_lecture_and_managed_audio_are_restorable(self):
        source = self.capture()
        lesson = self.lesson(source)
        self.assertEqual(library.list_recordings()[0].lesson_ids, (lesson.id,))
        deleted = library.archive_lesson(lesson.id)
        self.assertFalse(source.exists())
        self.assertFalse(Path(lesson.audio_path).exists())
        self.assertEqual(storage.list_lessons(self.subject.id), [])
        self.assertEqual(load_overview().lesson_count, 0)
        with self.assertRaises(storage.NotFoundError):
            storage.get_lesson(lesson.id)
        library.restore_item(deleted)
        restored = storage.get_lesson(lesson.id)
        self.assertEqual(restored.transcript, lesson.transcript)
        self.assertEqual(source.read_bytes(), b'capture original')
        self.assertEqual(Path(restored.audio_path).read_bytes(), b'capture original')
        self.assertEqual(library.list_trash(), [])

    def test_audio_only_keeps_text_and_external_original(self):
        lesson = self.lesson()
        item = library.archive_lesson(lesson.id, audio_only=True)
        stored = storage.get_lesson(lesson.id)
        self.assertEqual(stored.audio_path, '')
        self.assertEqual(stored.transcript, lesson.transcript)
        self.assertFalse(Path(lesson.audio_path).exists())
        self.assertTrue(self.source.exists())
        library.restore_item(item)
        self.assertEqual(storage.get_lesson(lesson.id).audio_path, lesson.audio_path)
        self.assertEqual(Path(lesson.audio_path).read_bytes(), self.source.read_bytes())

    def test_standalone_recording_round_trip(self):
        source = self.capture()
        item = library.archive_recording(source)
        self.assertFalse(source.exists())
        self.assertEqual(library.list_recordings(), [])
        library.restore_item(item)
        self.assertTrue(source.exists())

    def test_active_and_linked_files_cannot_be_deleted(self):
        source = self.capture()
        lesson = self.lesson(source)
        with self.assertRaises(storage.StorageError):
            library.archive_recording(source)
        storage.claim_lesson_for_transcription(lesson.id)
        with self.assertRaises(storage.StorageError):
            library.archive_lesson(lesson.id)
        with self.assertRaises(storage.StorageError):
            library.archive_lesson(lesson.id, audio_only=True)
        self.assertTrue(source.exists())
        self.assertTrue(Path(lesson.audio_path).exists())
        self.assertEqual(library.list_trash(), [])

    def test_rollback_restores_files_when_database_write_fails(self):
        lesson = self.lesson()
        real = storage._connect
        @contextmanager
        def fail(*args, **kwargs):
            with real(*args, **kwargs) as conn:
                yield conn
                raise sqlite3.OperationalError('simulated commit failure')
        with patch.object(storage, '_connect', fail):
            with self.assertRaises(sqlite3.OperationalError):
                library.archive_lesson(lesson.id)
        self.assertTrue(Path(lesson.audio_path).exists())
        self.assertEqual(storage.get_lesson(lesson.id).transcript, lesson.transcript)
        self.assertEqual(library.list_trash(), [])

    def test_shared_audio_stays_available_to_other_lesson(self):
        first = self.lesson()
        second = storage.create_lesson(self.subject.id, 'Вторая', first.audio_path)
        item = library.archive_lesson(first.id)
        self.assertTrue(Path(second.audio_path).exists())
        item2 = library.archive_lesson(second.id)
        with self.assertRaises(storage.StorageError):
            library.restore_item(item)
        library.restore_item(item2)
        library.restore_item(item)
        self.assertTrue(Path(storage.get_lesson(first.id).audio_path).exists())

    def test_symlinks_do_not_delete_external_files(self):
        link = storage.get_audio_dir() / 'link.wav'
        link.symlink_to(self.source)
        lesson = storage.create_lesson(self.subject.id, 'Ссылка', link)
        item = library.archive_lesson(lesson.id)
        self.assertTrue(self.source.exists())
        self.assertTrue(link.is_symlink())
        library.restore_item(item)
        with self.assertRaises(storage.StorageError):
            library.archive_recording(self.source)

    def test_restore_never_overwrites_existing_file(self):
        lesson = self.lesson()
        item = library.archive_lesson(lesson.id)
        Path(lesson.audio_path).write_bytes(b'new data')
        with self.assertRaises(storage.StorageError):
            library.restore_item(item)
        self.assertEqual(Path(lesson.audio_path).read_bytes(), b'new data')
        self.assertEqual(len(library.list_trash()), 1)

    def test_old_recording_source_is_found_by_filename_and_content(self):
        source = self.capture()
        lesson = self.lesson(source)
        with storage._connect() as conn:
            conn.execute('UPDATE lessons SET recording_path = NULL WHERE id = ?', (lesson.id,))
        self.assertEqual(library.list_recordings()[0].lesson_ids, (lesson.id,))
        library.archive_lesson(lesson.id)
        self.assertFalse(source.exists())

    def test_move_lecture_to_another_subject(self):
        lesson = self.lesson()
        other = storage.create_subject('Математика')
        moved = storage.update_lesson_details(lesson.id, other.id, 'Интегралы')
        self.assertEqual(storage.list_lessons(self.subject.id), [])
        self.assertEqual(storage.list_lessons(other.id)[0], moved)
        self.assertEqual(moved.transcript, lesson.transcript)

    def test_upgrade_old_schema_preserves_rows_and_is_idempotent(self):
        lesson = self.lesson()
        # Produce the previously deployed schema, without the new columns.
        with storage._connect() as conn:
            conn.execute('ALTER TABLE lessons DROP COLUMN recording_path')
            conn.execute('ALTER TABLE lessons DROP COLUMN deleted_at')
            conn.execute('DROP TABLE trash')
        storage.init_db(); storage.init_db()
        self.assertEqual(storage.get_lesson(lesson.id), lesson)
        self.assertEqual(library.list_trash(), [])


if __name__ == '__main__':
    unittest.main()
