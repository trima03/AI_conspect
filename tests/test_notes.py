import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from konspekt import storage, pipeline, notes, library


class CharacterTokenizer:
    def encode(self, text, **kwargs):
        return list(text)

    def apply_chat_template(self, messages, **kwargs):
        self.messages = messages
        return list('prompt')


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: self.temp.name})
        self.env.start()
        storage.init_db()
        subject = storage.create_subject('Физика')
        self.lesson = storage.create_lesson(subject.id, 'Законы Ньютона', 'unused.wav')
        self.source = 'Первый закон Ньютона: тело сохраняет покой или равномерное движение, если равнодействующая сил равна нулю.'
        storage.save_lesson_transcript(self.lesson.id, self.source)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def save_old(self):
        return storage.save_lesson_summary(self.lesson.id, '# Прежний конспект\n\nСохранённый текст.', source_transcript=self.source, model='old-model')

    def test_generated_notes_persist_with_model_and_source(self):
        result = notes.NotesResult('# Законы Ньютона\n\nПервый закон: инерция.', 'test-model', 1)
        with patch.object(notes, 'generate_notes', return_value=result) as engine:
            updated = pipeline.summarize_lesson(self.lesson.id)
        self.assertEqual(updated.summary, result.markdown)
        self.assertEqual(updated.transcript, self.source)
        self.assertEqual(updated.status, storage.STATUS_COMPLETED)
        self.assertEqual(engine.call_args.kwargs['subject'], 'Физика')
        state = storage.get_notes_state(self.lesson.id)
        self.assertEqual(state.source_hash, storage.transcript_hash(self.source))
        self.assertEqual(state.model, 'test-model')
        self.assertEqual(state.status, 'completed')

    def test_failure_keeps_previous_notes_and_transcript(self):
        old = self.save_old()
        with patch.object(notes, 'generate_notes', side_effect=notes.NotesError('Ошибка модели')):
            with self.assertRaises(notes.NotesError):
                pipeline.summarize_lesson(self.lesson.id)
        self.assertEqual(storage.get_lesson(self.lesson.id).summary, old.summary)
        self.assertEqual(storage.get_lesson(self.lesson.id).status, old.status)
        self.assertEqual(storage.get_notes_state(self.lesson.id).status, 'failed')

    def test_cancel_keeps_previous_notes_and_releases_claim(self):
        old = self.save_old()
        event = threading.Event()
        def cancel(*args, **kwargs):
            event.set()
            return notes.NotesResult('Не сохранять этот новый конспект', 'test', 1)
        with patch.object(notes, 'generate_notes', side_effect=cancel):
            with self.assertRaises(notes.NotesCancelled):
                pipeline.summarize_lesson(self.lesson.id, cancel_event=event)
        self.assertEqual(storage.get_lesson(self.lesson.id).summary, old.summary)
        self.assertEqual(storage.get_notes_state(self.lesson.id).status, 'cancelled')
        self.assertEqual(storage.get_lesson(self.lesson.id).status, storage.STATUS_COMPLETED)

    def test_changed_transcript_rejects_stale_generation(self):
        self.save_old()
        def edit_source(*args, **kwargs):
            storage.save_lesson_transcript(self.lesson.id, 'Новая расшифровка с другими фактами.')
            return notes.NotesResult('Конспект по старому тексту', 'test', 1)
        with patch.object(notes, 'generate_notes', side_effect=edit_source):
            with self.assertRaisesRegex(storage.StorageError, 'изменилась'):
                pipeline.summarize_lesson(self.lesson.id)
        updated = storage.get_lesson(self.lesson.id)
        self.assertIsNone(updated.summary)
        self.assertEqual(updated.status, storage.STATUS_COMPLETED)
        self.assertEqual(storage.get_notes_state(self.lesson.id).status, 'stale')

    def test_manual_edit_requires_same_source(self):
        self.save_old()
        with self.assertRaises(storage.StorageError):
            storage.save_lesson_summary(self.lesson.id, 'Новый конспект', source_transcript='Другая расшифровка')
        self.assertIn('Прежний', storage.get_lesson(self.lesson.id).summary)
        storage.save_lesson_summary(self.lesson.id, '# Исправлено\n\nПокой и инерция.', source_transcript=self.source)
        self.assertIn('Исправлено', storage.get_lesson(self.lesson.id).summary)

    def test_transcript_edits_invalidate_but_same_text_keeps_notes(self):
        old = self.save_old()
        storage.save_lesson_transcript(self.lesson.id, self.source)
        self.assertEqual(storage.get_lesson(self.lesson.id).summary, old.summary)
        storage.save_lesson_transcript(self.lesson.id, 'Изменено содержание лекции.')
        self.assertIsNone(storage.get_lesson(self.lesson.id).summary)
        self.assertEqual(storage.get_notes_state(self.lesson.id).status, 'stale')

    def test_concurrent_jobs_and_deletion_are_blocked(self):
        storage.claim_lesson_for_notes(self.lesson.id)
        with self.assertRaises(storage.StorageError):
            storage.claim_lesson_for_notes(self.lesson.id)
        with self.assertRaises(storage.StorageError):
            storage.claim_lesson_for_transcription(self.lesson.id)
        with self.assertRaises(storage.StorageError):
            library.archive_lesson(self.lesson.id)

    def test_reset_invalidates_old_generation_job(self):
        claim = storage.claim_lesson_for_notes(self.lesson.id)
        storage.set_lesson_status(self.lesson.id, storage.STATUS_QUEUED)
        with self.assertRaisesRegex(storage.StorageError, 'не активна'):
            storage.save_lesson_summary(self.lesson.id, 'Устаревший результат генерации', source_transcript=self.source, job_id=claim.job_id)
        self.assertEqual(storage.get_lesson(self.lesson.id).status, storage.STATUS_QUEUED)

    def test_empty_transcript_cannot_be_claimed(self):
        subject = storage.list_subjects()[0]
        lesson = storage.create_lesson(subject.id, 'Пусто', 'audio.wav')
        with self.assertRaises(storage.StorageError):
            pipeline.summarize_lesson(lesson.id)
        self.assertEqual(storage.get_lesson(lesson.id).status, storage.STATUS_QUEUED)

    def test_split_preserves_every_character_including_tail(self):
        source = ('Сложные формулы: ∫ x dx. 🤔\n' * 51) + 'ВАЖНЫЙ КОНЕЦ'
        parts = notes.split_text(source, CharacterTokenizer(), limit=73)
        self.assertEqual(''.join(parts), source)
        self.assertTrue(all(len(part) <= 73 for part in parts))
        self.assertTrue(parts[-1].endswith('ВАЖНЫЙ КОНЕЦ'))

    def test_long_text_map_reduce_covers_all_parts(self):
        source = 'НАЧАЛО. ' + 'Содержательная лекция. ' * 500 + 'ВАЖНЫЙ КОНЕЦ'
        original_parts = []
        def complete(text, **kwargs):
            if not kwargs['final']:
                original_parts.append(text)
                return '# Тезисы\n\nПолезные положения из фрагмента.'
            return '# Конспект\n\nСводный результат по всем фрагментам.'
        with patch.object(notes._LocalModel, 'load', return_value=(object(), CharacterTokenizer())), patch.object(notes, '_complete', side_effect=complete):
            result = notes.generate_notes(source)
        self.assertGreater(result.source_parts, 1)
        self.assertEqual(''.join(original_parts), source)

    def test_cancel_before_model_loading(self):
        event = threading.Event(); event.set()
        with patch.object(notes._LocalModel, 'load') as loader:
            with self.assertRaises(notes.NotesCancelled):
                notes.generate_notes(self.source, cancel_event=event)
            loader.assert_not_called()

    def test_truncated_generation_is_not_accepted(self):
        def stream(*args, **kwargs):
            yield SimpleNamespace(text='Незавершённый конспект обрывается', generation_tokens=1500, finish_reason='length')
        modules = {'mlx_lm': SimpleNamespace(stream_generate=stream),
                   'mlx_lm.sample_utils': SimpleNamespace(make_sampler=lambda **kwargs: None)}
        with patch.dict('sys.modules', modules):
            with self.assertRaisesRegex(notes.NotesError, 'предела длины'):
                notes._complete(self.source, model=object(), tokenizer=CharacterTokenizer(),
                                title='Тема', subject='Предмет', final=True, style='short', cancel_event=None, report=lambda message: None)

    def test_summary_survives_trash_restore(self):
        old = self.save_old()
        entry = library.archive_lesson(self.lesson.id)
        library.restore_item(entry)
        self.assertEqual(storage.get_lesson(self.lesson.id).summary, old.summary)
        self.assertEqual(storage.get_notes_state(self.lesson.id).status, 'completed')

    def test_model_download_cancellation_stops_only_child(self):
        from konspekt import notes_model
        event = threading.Event()
        class Child:
            returncode = None
            terminated = False
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def poll(self):
                event.set()
                return self.returncode
            def terminate(self):
                self.terminated = True
                self.returncode = -15
            def wait(self, **kwargs): return self.returncode
        child = Child()
        with patch.object(notes_model, '_cached', return_value=None), patch.object(notes_model.subprocess, 'Popen', return_value=child):
            with self.assertRaises(notes.NotesCancelled):
                notes_model.ensure_model(event, lambda message: None)
        self.assertTrue(child.terminated)

    def test_cancelled_model_download_does_not_start_child(self):
        from konspekt import notes_model
        event = threading.Event(); event.set()
        with patch.object(notes_model.subprocess, 'Popen') as process:
            with self.assertRaises(notes.NotesCancelled):
                notes_model.ensure_model(event, lambda message: None)
            process.assert_not_called()

    def test_partial_model_is_not_treated_as_ready(self):
        import json
        from konspekt import notes_model
        root = Path(self.temp.name)/'model'
        root.mkdir()
        for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json'):
            (root/name).write_text('{}')
        (root/'model.safetensors.index.json').write_text(json.dumps({'weight_map': {'a':'part1.safetensors','b':'part2.safetensors'}}))
        (root/'part1.safetensors').write_bytes(b'weights')
        self.assertFalse(notes_model._valid(root))
        (root/'part2.safetensors').write_bytes(b'weights')
        self.assertTrue(notes_model._valid(root))

    def test_saving_same_source_does_not_unlock_running_generation(self):
        storage.claim_lesson_for_notes(self.lesson.id)
        storage.save_lesson_transcript(self.lesson.id, self.source)
        self.assertEqual(storage.get_lesson(self.lesson.id).status, storage.STATUS_PROCESSING)
        with self.assertRaises(storage.StorageError):
            storage.claim_lesson_for_notes(self.lesson.id)
        with self.assertRaises(storage.StorageError):
            storage.save_lesson_summary(self.lesson.id, 'Ручной конкурирующий конспект', source_transcript=self.source)


if __name__ == '__main__':
    unittest.main()
