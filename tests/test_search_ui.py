import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from konspekt import storage, library
from konspekt.ui.pages.lessons_page import LessonsPage
from konspekt.ui.widgets import LessonRow
from konspekt.ui.main_window import MainWindow


class SearchUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {storage.DATA_DIR_ENV_VAR: self.temp.name})
        self.env.start()
        storage.init_db()
        self.math = storage.create_subject("Математика")
        self.physics = storage.create_subject("Физика")
        self.first = storage.create_lesson(self.math.id, "Первая лекция", "/missing.wav")
        self.second = storage.create_lesson(self.physics.id, "Вторая лекция", "/missing.wav")
        storage.save_lesson_transcript(self.first.id, "Предел последовательности.")
        self.page = LessonsPage()
        self.page.refresh()

    def tearDown(self):
        self.page._timer.stop()
        self.page.close()
        self.page.deleteLater()
        self.app.processEvents()
        self.env.stop()
        self.temp.cleanup()

    def visible_ids(self):
        return [row.property("lesson_id") for row in self.page.findChildren(LessonRow)]

    def test_debounced_search_and_open_use_matching_lesson_id(self):
        self.page.query.setText("ПРЕДЕЛ")
        QTest.qWait(250)
        self.assertEqual(self.visible_ids(), [self.first.id])
        self.assertEqual(self.page.result_count.text(), "Найдено лекций: 1")
        excerpt = self.page.findChild(QLabel, "SearchExcerpt")
        self.assertIn("Предел", excerpt.text())
        requested = []
        self.page.lesson_requested.connect(requested.append)
        row = self.page.findChild(LessonRow)
        next(button for button in row.findChildren(QPushButton) if button.text() == "Открыть").click()
        self.assertEqual(requested, [self.first.id])

    def test_filters_survive_refresh_and_reset_restores_all(self):
        self.page.subjects.setCurrentIndex(self.page.subjects.findData(self.math.id))
        self.page.statuses.setCurrentIndex(self.page.statuses.findData(storage.STATUS_COMPLETED))
        self.page.query.setText("предел")
        self.page.refresh()
        self.assertEqual(self.page.query.text(), "предел")
        self.assertEqual(self.page.subjects.currentData(), self.math.id)
        self.assertEqual(self.visible_ids(), [self.first.id])
        self.page.clear.click()
        self.assertEqual(self.visible_ids(), [self.second.id, self.first.id])
        self.assertEqual(self.page.query.text(), "")
        self.assertIsNone(self.page.statuses.currentData())

    def test_deleted_results_disappear_on_refresh(self):
        self.page.query.setText("предел")
        self.page._show_results()
        library.archive_lesson(self.first.id)
        self.page.refresh()
        self.assertEqual(self.visible_ids(), [])
        self.assertIn("Совпадений нет", " ".join(label.text() for label in self.page.findChildren(QLabel)))

    def test_user_markup_in_excerpt_stays_plain_text(self):
        storage.save_lesson_transcript(self.first.id, '<img src="file:///private.txt"> маркер')
        self.page.query.setText("маркер")
        self.page._show_results()
        excerpt = self.page.findChild(QLabel, "SearchExcerpt")
        self.assertEqual(excerpt.textFormat(), Qt.TextFormat.PlainText)
        self.assertIn("<img", excerpt.text())

    def test_search_navigation_uses_real_page_and_opens_matching_lesson(self):
        with patch.object(MainWindow, "_open_lesson") as open_lesson:
            window = MainWindow()
            try:
                window._nav_buttons[3].click()
                page = window._stack.currentWidget()
                self.assertIsInstance(page, LessonsPage)
                page.query.setText("предел")
                page._show_results()
                row = page.findChild(LessonRow)
                button = next(button for button in row.findChildren(QPushButton) if button.text() == "Открыть")
                button.click()
                open_lesson.assert_called_once_with(self.first.id)
            finally:
                window.close()
                window.deleteLater()
