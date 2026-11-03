"""Real FFmpeg checks on synthetic signals; no lecture or microphone is used."""
import hashlib
import os
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
from konspekt import transcription, pipeline, storage
from konspekt.transcribe import main


class NoiseReductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: str(self.root / "data")})
        self.env.start()
        storage.init_db()
        self.source = self.root / "classroom.wav"
        t = np.arange(4 * 16000) / 16000
        rng = np.random.default_rng(73)
        signal = .08 * np.sin(2 * np.pi * 50 * t) + .06 * np.sin(2 * np.pi * 1000 * t) + .003 * rng.normal(size=len(t))
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes((signal * 32767).astype('<i2').tobytes())

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def samples(self, path):
        with wave.open(str(path), "rb") as stream:
            self.assertEqual(stream.getnchannels(), 1)
            self.assertEqual(stream.getframerate(), 16000)
            return np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(float)

    def test_real_filter_reduces_hum_without_removing_speech_band_or_source(self):
        original_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        output = self.root / "filtered.wav"
        transcription._decode_audio(self.source, output, None, 20, reduce_noise=True)
        before, after = self.samples(self.source), self.samples(output)
        self.assertEqual(len(after), len(before))
        def amplitude(samples, frequency):
            tail = samples[16000:]
            spectrum = np.abs(np.fft.rfft(tail))
            return spectrum[round(frequency * len(tail) / 16000)]
        self.assertLess(amplitude(after, 50), amplitude(before, 50) * .4)
        self.assertGreater(amplitude(after, 1000), amplitude(before, 1000) * .3)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original_hash)

    def test_default_mode_leaves_pcm_samples_unchanged(self):
        output = self.root / "normal.wav"
        transcription._decode_audio(self.source, output, None, 20)
        np.testing.assert_array_equal(self.samples(self.source), self.samples(output))

    def test_noise_mode_reaches_decoder_and_keeps_timestamps(self):
        progress = []
        payload = {"text": "Учебный текст", "segments": [{"start": 0, "end": 2, "text": "Учебный текст"}]}
        with patch.object(transcription, '_recognize', return_value=payload):
            result = transcription.transcribe_audio(self.source, reduce_noise=True, progress=progress.append)
        self.assertEqual(result.text, "Учебный текст")
        self.assertEqual(result.segments[0].end, 2)
        self.assertTrue(any("шума" in message for message in progress))

    def test_pipeline_and_cli_forward_the_mode(self):
        subject = storage.create_subject("Физика")
        lesson = storage.create_lesson(subject.id, "Лекция", self.source)
        output = transcription.TranscriptionResult("Результат", "turbo")
        with patch.object(pipeline, 'transcribe_audio', return_value=output) as engine:
            pipeline.transcribe_lesson(lesson.id, reduce_noise=True)
        self.assertTrue(engine.call_args.kwargs['reduce_noise'])
        with patch('konspekt.transcribe.transcribe_audio', return_value=output) as engine:
            self.assertEqual(main([str(self.source), '--reduce-noise']), 0)
        self.assertTrue(engine.call_args.kwargs['reduce_noise'])
