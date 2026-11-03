import os
import tempfile
import unittest
from unittest.mock import patch

from konspekt import search, storage, library


class LessonSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: self.temp.name})
        self.env.start()
        storage.init_db()
        self.math = storage.create_subject("Математика")
        self.physics = storage.create_subject("Физика")

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def lesson(self, title="Лекция", subject=None, transcript=None, notes=None):
        lesson = storage.create_lesson(subject or self.math.id, title, "/missing.wav")
        if transcript:
            lesson = storage.save_lesson_transcript(lesson.id, transcript)
        if notes:
            lesson = storage.save_lesson_summary(lesson.id, notes, source_transcript=transcript)
        return lesson

    def ids(self, query="", **filters):
        return [item.lesson.id for item in search.search_lessons(query, **filters).matches]

    def test_searches_all_fields_and_combines_words_across_them(self):
        lesson = self.lesson("Производная", transcript="Предел отношения приращений.", notes="# Конспект\n\nКасательная к графику.")
        for query in ["производная", "математика", "предел", "касательная", "МАТЕМАТИКА предел касательная"]:
            self.assertEqual(self.ids(query), [lesson.id])
        self.assertEqual(self.ids("предел интеграл"), [])

    def test_cyrillic_case_yo_and_unicode_are_normalized(self):
        lesson = self.lesson("РАСЧЁТ Straße ＡＢＣ", transcript="Вычисление.")
        for query in ["расчет", "РАСЧЁТ", "strasse", "abc"]:
            self.assertEqual(self.ids(query), [lesson.id])

    def test_punctuation_and_sql_wildcards_are_literal(self):
        literal = self.lesson("100% _ и ' OR 1=1 --")
        other = self.lesson("Обычный текст")
        for query in ["100%", "_", "' OR 1=1 --"]:
            self.assertEqual(self.ids(query), [literal.id])
        self.assertEqual(self.ids("%_"), [])
        self.assertIn(other.id, self.ids())

    def test_filters_compose_with_query_and_keep_failed_lessons(self):
        first = self.lesson("Сила", self.physics.id, "Закон Ньютона")
        second = self.lesson("Сила", self.math.id)
        storage.set_lesson_status(first.id, storage.STATUS_FAILED, "Модель недоступна")
        self.assertEqual(self.ids("сила", subject_id=self.physics.id, status=storage.STATUS_FAILED), [first.id])
        self.assertEqual(self.ids("сила", status=storage.STATUS_QUEUED), [second.id])
        self.assertEqual(self.ids(subject_id=99999), [])

    def test_trash_is_excluded_and_restore_reappears(self):
        lesson = self.lesson("Искомая лекция")
        library.archive_lesson(lesson.id)
        self.assertEqual(self.ids("искомая"), [])
        library.restore_item(library.list_trash()[0].id)
        self.assertEqual(self.ids("искомая"), [lesson.id])

    def test_current_edits_are_searchable_without_an_index_refresh(self):
        lesson = self.lesson(transcript="Старая фраза", notes="# Конспект\n\nПрежний результат.")
        storage.save_lesson_transcript(lesson.id, "Новая фраза")
        self.assertEqual(self.ids("новая"), [lesson.id])
        self.assertEqual(self.ids("старая"), [])
        self.assertEqual(self.ids("прежний"), [])

    def test_excerpt_shows_match_near_end_and_keeps_original_spelling(self):
        text = "Вступление. " * 100 + "В конце рассмотрим РАСЧЁТ ускорения."
        lesson = self.lesson(transcript=text)
        result = search.search_lessons("расчет")
        self.assertEqual(result.total, 1)
        self.assertIn("РАСЧЁТ", result.matches[0].excerpt)
        self.assertIn("Расшифровка:", result.matches[0].excerpt)
        self.assertLess(len(result.matches[0].excerpt), 260)
        self.assertEqual(storage.get_lesson(lesson.id).transcript, text)

    def test_result_limit_does_not_hide_total_and_newest_are_first(self):
        for index in range(search.RESULT_LIMIT + 2):
            self.lesson(f"Лекция {index}")
        result = search.search_lessons()
        self.assertEqual(result.total, 102)
        self.assertEqual(len(result.matches), 100)
        self.assertEqual(result.matches[0].lesson.title, "Лекция 101")

    def test_empty_whitespace_and_invalid_queries(self):
        lesson = self.lesson()
        self.assertEqual(self.ids(" \n "), [lesson.id])
        self.assertEqual(search.search_lessons("нет").total, 0)
        for query in [None, 123, "а" * 201]:
            with self.assertRaises(ValueError):
                search.search_lessons(query)
        with self.assertRaises(ValueError):
            search.search_lessons(status="unknown")
