"""Цвета и стили интерфейса (QSS) в одном месте.

Чтобы поменять внешний вид, достаточно поправить цвета в COLORS
или правила в _QSS_TEMPLATE. В тексте стилей цвета записаны как @ИМЯ@
и подставляются из COLORS функцией build_stylesheet().
"""

from __future__ import annotations

COLORS = {
    # Основная (светлая) часть
    "BACKGROUND": "#F4F6FA",
    "CARD": "#FFFFFF",
    "BORDER": "#E5E7EB",
    "DIVIDER": "#EEF0F4",
    "TEXT": "#1F2937",
    "MUTED": "#6B7280",
    "ACCENT": "#4F6BED",
    "ACCENT_HOVER": "#3F59D6",
    "ACCENT_PRESSED": "#364DC0",
    "ACCENT_DISABLED": "#AAB6F5",
    "DANGER": "#B91C1C",
    # Боковая панель
    "SIDEBAR": "#1E2433",
    "SIDEBAR_TEXT": "#C9D1E0",
    "SIDEBAR_MUTED": "#7C879E",
    "SIDEBAR_HOVER": "#283049",
    "SIDEBAR_ACTIVE": "#323C5A",
    # Полосы прокрутки
    "SCROLL_HANDLE": "#CBD2DC",
    "SCROLL_HANDLE_HOVER": "#AEB7C4",
}

_QSS_TEMPLATE = """
/* ---------- Боковая панель ---------- */
#Sidebar {
    background-color: @SIDEBAR@;
}
#BrandTitle {
    color: #FFFFFF;
    font-size: 16pt;
    font-weight: 700;
}
#BrandSubtitle {
    color: @SIDEBAR_MUTED@;
    font-size: 9pt;
}
#SidebarFooter {
    color: @SIDEBAR_MUTED@;
    font-size: 8pt;
}
QPushButton#NavButton {
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 8px;
    background-color: transparent;
    color: @SIDEBAR_TEXT@;
    font-size: 10.5pt;
}
QPushButton#NavButton:hover {
    background-color: @SIDEBAR_HOVER@;
    color: #FFFFFF;
}
QPushButton#NavButton:checked {
    background-color: @SIDEBAR_ACTIVE@;
    color: #FFFFFF;
    font-weight: 600;
}

/* ---------- Основная область ---------- */
#ContentArea {
    background-color: @BACKGROUND@;
}
#PageTitle {
    color: @TEXT@;
    font-size: 20pt;
    font-weight: 600;
}
#PageSubtitle {
    color: @MUTED@;
    font-size: 10.5pt;
}
#SectionTitle {
    color: @TEXT@;
    font-size: 13pt;
    font-weight: 600;
}
#Muted {
    color: @MUTED@;
}
#HintText {
    color: @MUTED@;
    font-size: 9pt;
}
#RowTitle {
    color: @TEXT@;
    font-size: 11pt;
    font-weight: 600;
}
#RowError {
    color: @DANGER@;
    font-size: 9pt;
}
#EmptyTitle {
    color: @TEXT@;
    font-size: 12pt;
    font-weight: 600;
}
#StatValue {
    color: @TEXT@;
    font-size: 26pt;
    font-weight: 600;
}

/* ---------- Карточки и строки ---------- */
QFrame#Card {
    background-color: @CARD@;
    border: 1px solid @BORDER@;
    border-radius: 12px;
}
QFrame#LessonRow {
    background-color: transparent;
    border: none;
    border-bottom: 1px solid @DIVIDER@;
}

/* ---------- Кнопки ---------- */
QPushButton#PrimaryButton {
    background-color: @ACCENT@;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: @ACCENT_HOVER@;
}
QPushButton#PrimaryButton:pressed {
    background-color: @ACCENT_PRESSED@;
}
QPushButton#PrimaryButton:disabled {
    background-color: @ACCENT_DISABLED@;
}

/* ---------- Подсказки ---------- */
QToolTip {
    color: @TEXT@;
    background-color: #FFFFFF;
    border: 1px solid #D1D5DB;
    padding: 4px 8px;
}

/* ---------- Полосы прокрутки ---------- */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: @SCROLL_HANDLE@;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: @SCROLL_HANDLE_HOVER@;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


def build_stylesheet() -> str:
    """Возвращает готовый текст стилей с подставленными цветами."""
    stylesheet = _QSS_TEMPLATE
    for name, value in COLORS.items():
        stylesheet = stylesheet.replace(f"@{name}@", value)
    return stylesheet
