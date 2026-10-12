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

from .. import storage
from .pages.home_page import HomePage
from .pages.placeholder_page import PlaceholderPage

SIDEBAR_WIDTH = 232

# Названия разделов в боковой панели (порядок совпадает с порядком страниц).
NAV_TITLES = ("Главная", "Предметы", "Все лекции", "Поиск")


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
        self._pages = [
            self._home_page,
            PlaceholderPage(
                "Предметы",
                "Здесь будет список предметов и возможность создавать новые.",
            ),
            PlaceholderPage(
                "Все лекции",
                "Здесь будут все ваши лекции с датой и статусом.",
            ),
            PlaceholderPage(
                "Поиск",
                "Здесь можно будет искать лекции по названию и тексту.",
            ),
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
        # Окно добавления лекции появится на этапе 4.
        QMessageBox.information(
            self,
            "Добавление лекции",
            "Добавление лекций появится на одном из следующих этапов разработки.",
        )
