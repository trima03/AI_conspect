"""Regression checks use temporary storage, fake microphones, and fake models."""
import os
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from konspekt import audio, lesson_audio, pipeline, recording, storage, transcription


class LocalAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: str(self.root / 'data')})
        self.env.start()
        storage.init_db()
        self.subject = storage.create_subject('Математика')
        self.wav = self.root / 'source.wav'
        with wave.open(str(self.wav), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes((np.sin(np.arange(16000) * .1) * 1200).astype('<i2').tobytes())

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def lesson(self):
        return lesson_audio.create_lesson_with_audio(self.subject.id, 'Производные', self.wav)

    def test_real_ffmpeg_decoding_and_chunk_timestamps(self):
        progress = []
        with wave.open(str(self.wav), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
            output.writeframes(np.full(48000, 100, dtype='<i2').tobytes())
        def recognize(samples, **kwargs):
            self.assertEqual(len(samples), 16000)
            return {'text': 'Слово', 'segments': [{'start': 0, 'end': 1, 'text': 'Слово'}]}
        with patch.object(transcription, '_recognize', side_effect=recognize), patch.object(transcription, 'CHUNK_SECONDS', 1):
            result = transcription.transcribe_audio(self.wav, progress=progress.append)
        self.assertEqual([s.start for s in result.segments], [0, 1, 2])
        self.assertEqual(len(result.text.split()), 3)
        self.assertTrue(progress[-1].endswith('готова.'))

    def test_silence_does_not_call_model(self):
        with wave.open(str(self.wav), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
            output.writeframes(bytes(32000))
        with patch.object(transcription, '_recognize') as model:
            with self.assertRaisesRegex(transcription.TranscriptionError, 'Речь не обнаружена'):
                transcription.transcribe_audio(self.wav)
            model.assert_not_called()

    def test_corrupt_audio_and_missing_file(self):
        bad = self.root / 'broken.mp3'; bad.write_bytes(b'not an audio file')
        with self.assertRaisesRegex(transcription.TranscriptionError, 'Не удалось прочитать аудио'):
            transcription.transcribe_audio(bad)
        with self.assertRaisesRegex(transcription.TranscriptionError, 'не найден'):
            transcription.transcribe_audio(self.root / 'missing.wav')

    def test_duration_limit_is_checked_before_model(self):
        with patch.object(transcription, 'MAX_DURATION_SECONDS', .5), patch.object(transcription, '_recognize') as engine:
            with self.assertRaisesRegex(transcription.TranscriptionError, 'Максимальная длительность'):
                transcription.transcribe_audio(self.wav)
            engine.assert_not_called()

    def test_local_upload_can_exceed_old_limit(self):
        large = self.root / 'long.wav'
        with large.open('wb') as out:
            out.truncate(audio.MAX_SIZE_BYTES + 1)
        with self.assertRaises(audio.AudioTooLargeError):
            audio.save_audio(large)
        lesson = lesson_audio.create_lesson_with_audio(self.subject.id, 'Длинная лекция', large,
                                                      max_size_bytes=transcription.MAX_FILE_BYTES)
        self.assertEqual(Path(lesson.audio_path).stat().st_size, large.stat().st_size)

    def test_success_is_persisted_and_error_cleared(self):
        lesson = self.lesson()
        storage.set_lesson_status(lesson.id, storage.STATUS_FAILED, 'Старая ошибка')
        with patch.object(pipeline, 'transcribe_audio', return_value=transcription.TranscriptionResult('Производная', 'tiny')):
            result = pipeline.transcribe_lesson(lesson.id, model='tiny')
        self.assertEqual(storage.get_lesson(lesson.id), result)
        self.assertEqual(result.transcript, 'Производная')
        self.assertEqual(result.status, storage.STATUS_COMPLETED)
        self.assertIsNone(result.error_message)
        self.assertTrue(Path(result.audio_path).is_file())

    def test_failure_preserves_previous_transcript_and_audio(self):
        lesson = self.lesson()
        storage.save_lesson_transcript(lesson.id, 'Прежний текст')
        with patch.object(pipeline, 'transcribe_audio', side_effect=transcription.TranscriptionError('Нет модели')):
            with self.assertRaises(transcription.TranscriptionError):
                pipeline.transcribe_lesson(lesson.id)
        result = storage.get_lesson(lesson.id)
        self.assertEqual(result.status, storage.STATUS_FAILED)
        self.assertEqual(result.transcript, 'Прежний текст')
        self.assertEqual(result.error_message, 'Нет модели')
        self.assertTrue(Path(result.audio_path).is_file())

    def test_cancel_does_not_publish_text(self):
        lesson = self.lesson()
        stop = threading.Event()
        def recognize(*args, **kwargs):
            stop.set()
            return transcription.TranscriptionResult('Не сохранять', 'tiny')
        with patch.object(pipeline, 'transcribe_audio', side_effect=recognize):
            with self.assertRaises(transcription.TranscriptionCancelled):
                pipeline.transcribe_lesson(lesson.id, cancel_event=stop)
        result = storage.get_lesson(lesson.id)
        self.assertEqual(result.status, storage.STATUS_QUEUED)
        self.assertIsNone(result.transcript)

    def test_concurrent_claim_is_rejected(self):
        lesson = self.lesson()
        storage.claim_lesson_for_transcription(lesson.id)
        with patch.object(pipeline, 'transcribe_audio') as engine:
            with self.assertRaises(storage.StorageError):
                pipeline.transcribe_lesson(lesson.id)
            engine.assert_not_called()
        self.assertEqual(storage.get_lesson(lesson.id).status, storage.STATUS_PROCESSING)

    def test_cancel_before_decode(self):
        stop = threading.Event(); stop.set()
        with patch.object(transcription, '_decode_audio') as decoder:
            with self.assertRaises(transcription.TranscriptionCancelled):
                transcription.transcribe_audio(self.wav, cancel_event=stop)
            decoder.assert_not_called()

    def fake_sounddevice(self, stop, overflow_after=None):
        class Input:
            calls = 0
            active = True
            read_available = 100
            def __enter__(self): return self
            def __exit__(self, *args): self.active = False
            def read(self, frames):
                self.calls += 1
                if self.calls == 3:
                    stop.set()
                return np.full(frames, 1000, dtype='int16').tobytes(), self.calls == overflow_after
        return SimpleNamespace(query_devices=lambda *args: {'default_samplerate': 1000, 'max_input_channels': 1},
                               RawInputStream=lambda **kwargs: Input())

    def test_recording_stops_and_wav_header_is_finalized(self):
        stop = threading.Event(); levels = []
        with patch.object(recording, '_sounddevice', return_value=self.fake_sounddevice(stop)):
            result = recording.record_audio(stop, directory=self.root / 'capture', progress=lambda *args: levels.append(args))
        with wave.open(str(result), 'rb') as captured:
            self.assertEqual(captured.getnframes(), 300)
            self.assertEqual(captured.getframerate(), 1000)
        self.assertEqual(levels[-1][0], .3)
        self.assertGreater(levels[-1][1], 0)

    def test_recording_failure_keeps_playable_partial_audio(self):
        stop = threading.Event()
        with patch.object(recording, '_sounddevice', return_value=self.fake_sounddevice(stop, overflow_after=2)):
            with self.assertRaisesRegex(recording.RecordingError, 'Часть записи сохранена'):
                recording.record_audio(stop, directory=self.root / 'capture')
        saved = list((self.root / 'capture').glob('*.wav'))
        self.assertEqual(len(saved), 1)
        with wave.open(str(saved[0]), 'rb') as captured:
            self.assertEqual(captured.getnframes(), 100)

    def test_no_microphone_creates_no_files(self):
        bad = SimpleNamespace(query_devices=lambda *args: (_ for _ in ()).throw(RuntimeError('no microphone')))
        with patch.object(recording, '_sounddevice', return_value=bad):
            with self.assertRaisesRegex(recording.RecordingError, 'разрешение'):
                recording.record_audio(threading.Event(), directory=self.root / 'capture')
        self.assertFalse((self.root / 'capture').exists())

    def test_long_chunk_prefers_silence_and_never_cuts_last_tail(self):
        samples = np.ones(12 * transcription.SAMPLE_RATE, dtype=np.float32) * .1
        samples[-2 * transcription.SAMPLE_RATE:-transcription.SAMPLE_RATE] = 0
        cut = transcription._chunk_cut(samples, is_final=False)
        self.assertLess(cut, len(samples))
        self.assertGreaterEqual(cut, len(samples) - 3 * transcription.SAMPLE_RATE)
        self.assertEqual(transcription._chunk_cut(samples, is_final=True), len(samples))
        self.assertEqual(transcription._chunk_cut(np.ones_like(samples), is_final=False), len(samples))

    def test_background_noise_is_not_transcribed_as_speech(self):
        with wave.open(str(self.wav), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
            output.writeframes(np.ones(16000, dtype='<i2').tobytes())
        with patch.object(transcription, '_recognize') as model:
            with self.assertRaisesRegex(transcription.TranscriptionError, 'Речь не обнаружена'):
                transcription.transcribe_audio(self.wav)
            model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
