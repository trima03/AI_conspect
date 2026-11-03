"""Маленькие повторно используемые детали интерфейса.

Карточка, значок статуса, строка лекции, «пустое состояние», заголовок
страницы и страница с прокруткой. Страницы собираются из этих деталей.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import storage
from .formatting import shorten, status_style


class Card(QFrame):
    """Белая карточка с закруглёнными углами (внешний вид задан в styles.py)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")


class StatusBadge(QLabel):
    """Цветной значок статуса лекции: «В очереди», «Готово» и т.д."""

    def __init__(self, status: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        style = status_style(status)
        self.setText(style.text)
        self.setToolTip(style.hint)
        self.setStyleSheet(
            f"background-color: {style.background}; color: {style.foreground};"
            " border-radius: 10px; padding: 3px 12px;"
            " font-weight: 600; font-size: 9pt;"
        )


class EmptyState(QWidget):
    """Сообщение «здесь пока пусто»: заголовок и пояснение по центру."""

    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("EmptyTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        text_label = QLabel(text)
        text_label.setObjectName("Muted")
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_label.setWordWrap(True)
        layout.addWidget(text_label)


class PageHeader(QWidget):
    """Заголовок страницы с необязательным пояснением под ним."""

    def __init__(
        self, title: str, subtitle: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PageSubtitle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)


class LessonRow(QFrame):
    """Строка списка: название лекции, «предмет · дата» и значок статуса."""

    def __init__(
        self,
        title: str,
        meta: str,
        status: str,
        error_message: str | None = None,
        parent: QWidget | None = None,
        *,
        preview: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LessonRow")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 12, 0, 12)
        row.setSpacing(12)

        texts = QVBoxLayout()
        texts.setSpacing(2)

        # PlainText: названия и ошибки показываем как есть, без разбора HTML.
        title_label = QLabel(title)
        title_label.setObjectName("RowTitle")
        title_label.setTextFormat(Qt.TextFormat.PlainText)
        title_label.setWordWrap(True)
        texts.addWidget(title_label)

        meta_label = QLabel(meta)
        meta_label.setObjectName("Muted")
        meta_label.setTextFormat(Qt.TextFormat.PlainText)
        texts.addWidget(meta_label)

        if preview:
            preview_label = QLabel(preview)
            preview_label.setObjectName("SearchExcerpt")
            preview_label.setTextFormat(Qt.TextFormat.PlainText)
            preview_label.setWordWrap(True)
            texts.addWidget(preview_label)

        if status == storage.STATUS_FAILED and error_message:
            error_label = QLabel(shorten(error_message))
            error_label.setObjectName("RowError")
            error_label.setTextFormat(Qt.TextFormat.PlainText)
            error_label.setWordWrap(True)
            texts.addWidget(error_label)

        row.addLayout(texts, 1)
        row.addWidget(StatusBadge(status), 0, Qt.AlignmentFlag.AlignVCenter)


class ScrollPage(QWidget):
    """Страница с вертикальной прокруткой.

    Свои виджеты добавляйте в self.body (это QVBoxLayout с отступами страницы).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setObjectName("PageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        # Без этого область прокрутки закрашивает фон серым и закрывает фон страницы.
        content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)

        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(32, 28, 32, 28)
        self.body.setSpacing(20)
