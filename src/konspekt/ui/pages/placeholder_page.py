"""Временная страница для разделов, которые появятся на следующих этапах."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from ..widgets import Card, EmptyState, PageHeader, ScrollPage


class PlaceholderPage(ScrollPage):
    """Заголовок и сообщение «раздел появится позже»."""

    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.body.addWidget(PageHeader(title))

        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(EmptyState("Раздел появится на следующих этапах", text))
        self.body.addWidget(card)
        self.body.addStretch(1)

    def refresh(self) -> None:
        """Данных на этой странице пока нет, обновлять нечего."""
