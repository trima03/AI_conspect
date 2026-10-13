"""Offscreen Qt flows: no real microphone or model is used here."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication
    from konspekt.ui.audio_dialog import AudioDialog
    from konspekt.ui.main_window import MainWindow
except ImportError:
    QApplication = None

from konspekt import storage, pipeline
from konspekt.transcription import TranscriptionResult


@unittest.skipIf(QApplication is None, 'Install the desktop extra to test the UI')
class AudioUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: str(self.root / 'data')})
        self.env.start()
        storage.init_db()
        storage.create_subject('Матанализ')
        self.wav = self.root / 'recording.wav'
        self.wav.write_bytes(b'fake WAV for integration')
        self.devices = patch('konspekt.ui.audio_dialog.list_input_devices', return_value=[(0, 'Тестовый микрофон')])
        self.devices.start()
        self.dialog = AudioDialog()
        self.dialog.title.setText('Лекция')
        self.dialog._set_source(self.wav)
        self.dialog._busy(False)

    def tearDown(self):
        if self.dialog.job:
            self.dialog.job.stop_event.set()
            self.dialog.job.wait(5000)
            self.app.processEvents()
        self.dialog.close()
        self.app.processEvents()
        self.devices.stop()
        self.env.stop()
        self.temp.cleanup()

    def wait_done(self):
        deadline = time.monotonic() + 5
        while self.dialog.job is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(self.dialog.job, 'background worker did not finish')

    def test_import_processing_and_reopen(self):
        with patch.object(pipeline, 'transcribe_audio', return_value=TranscriptionResult('Производная функции', 'tiny')):
            self.dialog._transcribe()
            self.assertFalse(self.dialog.choose.isEnabled())
            self.wait_done()
        lesson = storage.get_lesson(self.dialog.lesson_id)
        self.assertEqual(lesson.transcript, self.dialog.text.toPlainText())
        self.assertEqual(lesson.status, storage.STATUS_COMPLETED)
        reopened = AudioDialog(lesson.id)
        self.assertEqual(reopened.text.toPlainText(), 'Производная функции')
        reopened.close()
        self.dialog.text.setPlainText('Исправленный текст')
        self.dialog._save()
        self.assertEqual(storage.get_lesson(lesson.id).transcript, 'Исправленный текст')
        window = MainWindow()
        window._show_page(2)
        self.assertEqual(window._stack.currentIndex(), 2)
        window.close()

    def test_record_then_transcribe(self):
        def fake_record(stop, **kwargs):
            kwargs['progress'](2.0, .5)
            return self.wav
        with patch('konspekt.ui.audio_dialog.record_audio', side_effect=fake_record), patch.object(
            pipeline, 'transcribe_audio', return_value=TranscriptionResult('Текст с микрофона', 'tiny')
        ):
            self.dialog._record()
            self.wait_done()
        self.assertEqual(storage.get_lesson(self.dialog.lesson_id).transcript, 'Текст с микрофона')
        self.assertEqual(self.dialog.level.value(), 50)

    def test_cancel_and_close_guard(self):
        started = threading.Event()
        def recognize(*args, **kwargs):
            started.set()
            kwargs['cancel_event'].wait(3)
            return TranscriptionResult('Не сохранять', 'tiny')
        with patch.object(pipeline, 'transcribe_audio', side_effect=recognize):
            self.dialog._transcribe()
            self.assertTrue(started.wait(2))
            self.dialog.reject()
            self.assertIsNotNone(self.dialog.job)
            self.dialog._cancel()
            self.wait_done()
        lesson = storage.get_lesson(self.dialog.lesson_id)
        self.assertEqual(lesson.status, storage.STATUS_QUEUED)
        self.assertIsNone(lesson.transcript)
        self.assertTrue(self.dialog.transcribe.isEnabled())


if __name__ == '__main__':
    unittest.main()
