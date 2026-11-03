"""Главное окно: боковая панель и переключение страниц."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import storage, library
from pathlib import Path
from .pages.home_page import HomePage
from .pages.lessons_page import LessonsPage
from .pages.subjects_page import SubjectsPage
from .pages.recordings_page import RecordingsPage
from .pages.trash_page import TrashPage
from .audio_dialog import AudioDialog

SIDEBAR_WIDTH = 232

# Названия разделов в боковой панели (порядок совпадает с порядком страниц).
NAV_TITLES = ("Главная", "Предметы", "Все лекции", "Поиск", "Записи", "Корзина")


class MainWindow(QMainWindow):
    """Окно приложения. Страницы лежат в QStackedWidget, видна одна из них."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = "AIKonspekt"
        if os.environ.get(storage.DATA_DIR_ENV_VAR):
            # Подсказка: данные не из настоящей папки проекта, а из указанной.
            title += " — тестовые данные"
        self.setWindowTitle(title)
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        # Страницы (позже заглушки заменим настоящими).
        self._home_page = HomePage()
        self._lessons_page = LessonsPage()
        self._search_page = LessonsPage(title="Поиск")
        self._subjects_page = SubjectsPage()
        self._recordings_page = RecordingsPage()
        self._trash_page = TrashPage()
        self._pages = [
            self._home_page,
            self._subjects_page,
            self._lessons_page,
            self._search_page,
            self._recordings_page,
            self._trash_page,
        ]
        self._stack = QStackedWidget()
        for page in self._pages:
            self._stack.addWidget(page)

        # Общая раскладка: слева панель, справа содержимое.
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._nav_buttons: list[QPushButton] = []
        root.addWidget(self._build_sidebar())

        content = QFrame()
        content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._stack)
        root.addWidget(content, 1)

        self._home_page.add_lesson_requested.connect(self._on_add_lesson_requested)
        self._home_page.lesson_requested.connect(self._open_lesson)
        self._lessons_page.lesson_requested.connect(self._open_lesson)
        self._search_page.lesson_requested.connect(self._open_lesson)
        self._subjects_page.lesson_requested.connect(self._open_lesson)
        self._subjects_page.add_requested.connect(lambda subject_id: self._open_lesson(subject_id=subject_id))
        self._subjects_page.changed.connect(self._refresh_all)
        self._recordings_page.lesson_requested.connect(self._open_lesson)
        self._recordings_page.recording_requested.connect(lambda path: self._open_lesson(source_path=path))
        self._recordings_page.delete_requested.connect(self._delete_recording)
        self._trash_page.restore_requested.connect(self._restore)
        for page in (self._home_page, self._lessons_page, self._search_page, self._subjects_page):
            page.delete_requested.connect(self._delete_lesson)
        self._show_page(0)

    # ------------------------------------------------------------------

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 24, 16, 20)
        layout.setSpacing(4)

        brand = QLabel("AIKonspekt")
        brand.setObjectName("BrandTitle")
        brand_subtitle = QLabel("Конспекты лекций")
        brand_subtitle.setObjectName("BrandSubtitle")
        layout.addWidget(brand)
        layout.addWidget(brand_subtitle)
        layout.addSpacing(24)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, nav_title in enumerate(NAV_TITLES):
            button = QPushButton(nav_title)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            # i=index запоминает номер именно этой кнопки.
            button.clicked.connect(lambda checked=False, i=index: self._show_page(i))
            group.addButton(button, index)
            layout.addWidget(button)
            self._nav_buttons.append(button)

        layout.addStretch(1)

        footer = QLabel("Данные хранятся\nна этом компьютере")
        footer.setObjectName("SidebarFooter")
        layout.addWidget(footer)
        return sidebar

    def _show_page(self, index: int) -> None:
        """Открывает страницу: обновляет её данные и подсвечивает пункт меню."""
        self._pages[index].refresh()
        self._stack.setCurrentIndex(index)
        self._nav_buttons[index].setChecked(True)

    def _on_add_lesson_requested(self) -> None:
        self._open_lesson()

    def _open_lesson(self, lesson_id=None, subject_id=None, source_path=None) -> None:
        try:
            dialog = AudioDialog(lesson_id, self, subject_id=subject_id, source_path=source_path)
            dialog.lesson_changed.connect(self._refresh_all)
            dialog.exec()
            dialog.deleteLater()
        except Exception as error:
            QMessageBox.warning(self, "Лекция", str(error))
        self._show_page(self._stack.currentIndex())

    def _refresh_all(self):
        for page in self._pages:
            page.refresh()

    def _delete_lesson(self, lesson_id):
        lesson = storage.get_lesson(lesson_id)
        if QMessageBox.question(self, "Удалить лекцию", f"Переместить «{lesson.title}» и её аудио в корзину?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._library_action(lambda: library.archive_lesson(lesson_id))

    def _delete_recording(self, path):
        if QMessageBox.question(self, "Удалить запись", "Переместить запись в корзину?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._library_action(lambda: library.archive_recording(Path(path)))

    def _restore(self, trash_id):
        self._library_action(lambda: library.restore_item(trash_id))

    def _library_action(self, action):
        try:
            action()
            self._refresh_all()
        except Exception as error:
            QMessageBox.warning(self, "Лекция или запись", str(error))
