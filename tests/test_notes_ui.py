import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QFileDialog
from konspekt import storage, notes, pipeline
from konspekt.transcription import TranscriptionResult
from konspekt.ui.audio_dialog import AudioDialog


class NotesUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: self.temp.name})
        self.env.start(); storage.init_db()
        subject = storage.create_subject('Физика')
        self.audio = Path(self.temp.name)/'audio.wav'; self.audio.write_bytes(b'fake audio')
        self.lesson = storage.create_lesson(subject.id, 'Сила', self.audio)
        storage.save_lesson_transcript(self.lesson.id, 'Сила равна произведению массы и ускорения. F = ma.')
        self.devices = patch('konspekt.ui.audio_dialog.list_input_devices', return_value=[])
        self.devices.start()
        self.dialog = AudioDialog(self.lesson.id)

    def tearDown(self):
        if self.dialog.job:
            self.dialog.job.stop_event.set(); self.dialog.job.wait(5000)
            self.app.processEvents()
        self.dialog.close(); self.app.processEvents()
        self.devices.stop(); self.env.stop(); self.temp.cleanup()

    def wait_done(self):
        until = time.monotonic()+5
        while self.dialog.job is not None and time.monotonic()<until:
            self.app.processEvents(); time.sleep(.01)
        self.assertIsNone(self.dialog.job)

    def test_generate_edit_export_reopen(self):
        output = notes.NotesResult('# Сила\n\n## Формула\n\nF = ma.', 'test-model', 1)
        with patch.object(notes, 'generate_notes', return_value=output):
            self.dialog._generate_notes()
            self.assertFalse(self.dialog.delete_lesson.isEnabled())
            self.wait_done()
        self.assertEqual(self.dialog.tabs.currentIndex(), 1)
        self.assertIn('F = ma', self.dialog.notes.toPlainText())
        self.assertEqual(storage.get_lesson(self.lesson.id).summary, output.markdown)
        self.dialog.notes.setMarkdown('# Правки\n\nСила измеряется в ньютонах.')
        self.dialog._save_notes()
        exported = Path(self.temp.name)/'notes.md'
        with patch.object(QFileDialog, 'getSaveFileName', return_value=(str(exported), 'Markdown (*.md)')):
            self.dialog._export()
        self.assertIn('Правки', exported.read_text())
        reopened = AudioDialog(self.lesson.id)
        self.assertIn('Правки', reopened.notes.toPlainText())
        reopened.close()

    def test_source_edit_clears_old_notes_in_ui(self):
        storage.save_lesson_summary(self.lesson.id, '# Старые заметки\n\nСтарое содержимое.', source_transcript=storage.get_lesson(self.lesson.id).transcript)
        self.dialog.close(); self.dialog = AudioDialog(self.lesson.id)
        self.dialog.text.setPlainText('Новая версия расшифровки с другими фактами.')
        self.dialog._save()
        self.assertFalse(self.dialog.notes.toPlainText().strip())
        self.assertIsNone(storage.get_lesson(self.lesson.id).summary)

    def test_cancel_preserves_displayed_and_stored_notes(self):
        source = storage.get_lesson(self.lesson.id).transcript
        old = storage.save_lesson_summary(self.lesson.id, '# Прежний конспект\n\nТекст.', source_transcript=source)
        self.dialog.close(); self.dialog = AudioDialog(self.lesson.id)
        started = threading.Event()
        def complete(*args, **kwargs):
            started.set(); kwargs['cancel_event'].wait(3)
            raise notes.NotesCancelled('Отмена')
        with patch.object(notes, 'generate_notes', side_effect=complete):
            self.dialog._generate_notes(); self.assertTrue(started.wait(2))
            self.dialog._cancel(); self.wait_done()
        self.assertEqual(storage.get_lesson(self.lesson.id).summary, old.summary)
        self.assertIn('Прежний', self.dialog.notes.toPlainText())

    def test_optional_audio_to_transcript_to_notes(self):
        self.dialog.auto_notes.setChecked(True)
        output = notes.NotesResult('# Новый конспект\n\nСила и движение.', 'test-model', 1)
        with patch.object(pipeline, 'transcribe_audio', return_value=TranscriptionResult('Новая расшифровка лекции.', 'tiny')), patch.object(notes, 'generate_notes', return_value=output):
            self.dialog._transcribe(); self.wait_done()
        result = storage.get_lesson(self.lesson.id)
        self.assertEqual(result.transcript, 'Новая расшифровка лекции.')
        self.assertEqual(result.summary, output.markdown)


if __name__ == '__main__':
    unittest.main()
