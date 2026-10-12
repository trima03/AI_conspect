"""Главная страница: приветствие, счётчики и последние лекции."""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..formatting import format_datetime, greeting_for_hour, plural_ru
from ..overview import Overview, load_overview
from ..widgets import Card, EmptyState, LessonRow, ScrollPage

logger = logging.getLogger(__name__)

RECENT_LIMIT = 5  # сколько последних лекций показывать


class HomePage(ScrollPage):
    """Главная страница. Данные читаются заново при каждом вызове refresh()."""

    # Страница не знает, как добавлять лекции: она только сообщает об этом окну.
    add_lesson_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # --- Верхняя строка: приветствие и кнопка ---
        top = QHBoxLayout()
        top.setSpacing(16)

        titles = QVBoxLayout()
        titles.setSpacing(4)
        self._greeting_label = QLabel()
        self._greeting_label.setObjectName("PageTitle")
        subtitle = QLabel("Загружайте записи лекций и храните конспекты в одном месте.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(self._greeting_label)
        titles.addWidget(subtitle)
        top.addLayout(titles, 1)

        add_button = QPushButton("+ Добавить лекцию")
        add_button.setObjectName("PrimaryButton")
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.clicked.connect(self._emit_add_lesson_requested)
        top.addWidget(add_button, 0, Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(top)

        # --- Счётчики ---
        stats = QHBoxLayout()
        stats.setSpacing(16)
        subjects_card, self._subjects_value, self._subjects_caption = self._make_stat_card()
        lessons_card, self._lessons_value, self._lessons_caption = self._make_stat_card()
        stats.addWidget(subjects_card)
        stats.addWidget(lessons_card)
        stats.addStretch(1)
        self.body.addLayout(stats)

        # --- Последние лекции ---
        recent_card = Card()
        recent_layout = QVBoxLayout(recent_card)
        recent_layout.setContentsMargins(24, 20, 24, 20)
        recent_layout.setSpacing(4)

        section_title = QLabel("Последние лекции")
        section_title.setObjectName("SectionTitle")
        recent_layout.addWidget(section_title)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(0)
        recent_layout.addLayout(self._rows_layout)

        self._hint_label = QLabel(
            "Расшифровка в этой версии пока не запускается: "
            "новые лекции остаются в очереди."
        )
        self._hint_label.setObjectName("HintText")
        self._hint_label.setWordWrap(True)
        recent_layout.addWidget(self._hint_label)

        self.body.addWidget(recent_card)
        self.body.addStretch(1)

    # ------------------------------------------------------------------

    @staticmethod
    def _make_stat_card() -> tuple[Card, QLabel, QLabel]:
        """Карточка со счётчиком: крупное число и подпись под ним."""
        card = Card()
        card.setMinimumWidth(190)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(0)

        value = QLabel("—")
        value.setObjectName("StatValue")
        caption = QLabel("")
        caption.setObjectName("Muted")
        layout.addWidget(value)
        layout.addWidget(caption)
        return card, value, caption

    def _emit_add_lesson_requested(self) -> None:
        self.add_lesson_requested.emit()

    def _clear_rows(self) -> None:
        """Убирает все строки из списка последних лекций."""
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Перечитывает данные из хранилища и обновляет страницу."""
        self._greeting_label.setText(f"{greeting_for_hour(datetime.now().hour)}!")
        try:
            overview = load_overview(RECENT_LIMIT)
        except Exception:
            # Пользователю показываем короткое сообщение, подробности пишем в журнал.
            logger.exception("Не удалось загрузить данные для главной страницы")
            self._show_load_error()
            return
        self._show_overview(overview)

    def _show_overview(self, overview: Overview) -> None:
        self._subjects_value.setText(str(overview.subject_count))
        self._subjects_caption.setText(
            plural_ru(overview.subject_count, "предмет", "предмета", "предметов")
        )
        self._lessons_value.setText(str(overview.lesson_count))
        self._lessons_caption.setText(
            plural_ru(overview.lesson_count, "лекция", "лекции", "лекций")
        )

        self._clear_rows()
        if not overview.recent:
            self._rows_layout.addWidget(
                EmptyState(
                    "Лекций пока нет",
                    "Когда вы добавите первую лекцию, она появится здесь.",
                )
            )
            self._hint_label.hide()
            return

        for item in overview.recent:
            meta = f"{item.subject_name} · {format_datetime(item.created_at)}"
            self._rows_layout.addWidget(
                LessonRow(item.title, meta, item.status, item.error_message)
            )
        self._hint_label.show()

    def _show_load_error(self) -> None:
        for label in (
            self._subjects_value,
            self._lessons_value,
        ):
            label.setText("—")
        self._subjects_caption.setText("")
        self._lessons_caption.setText("")

        self._clear_rows()
        self._rows_layout.addWidget(
            EmptyState(
                "Не удалось загрузить данные",
                "Подробности записаны в журнал (папка data/logs). "
                "Попробуйте перезапустить приложение.",
            )
        )
        self._hint_label.hide()
