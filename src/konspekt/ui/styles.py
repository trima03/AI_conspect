"""Цвета и стили интерфейса (QSS) в одном месте. Тема Dark Pro.

Чтобы поменять внешний вид, достаточно поправить цвета в COLORS
или правила в _QSS_TEMPLATE. В тексте стилей цвета записаны как @ИМЯ@
и подставляются из COLORS функцией build_stylesheet().

Этот модуль не зависит от Qt: его проверяет check_ui_theme.py без PySide6.
"""

from __future__ import annotations

COLORS = {
    # Основные поверхности: фон окна, панель, карточки
    "BACKGROUND": "#111318",
    "SURFACE": "#181A22",
    "CARD": "#1F222C",
    "BORDER": "#303442",
    "DIVIDER": "#2A2E3B",
    # Поля ввода и обычные кнопки
    "INPUT_BG": "#181A22",
    "INPUT_BORDER": "#4A5066",
    "BUTTON": "#262A36",
    "BUTTON_HOVER": "#2E3342",
    "BUTTON_PRESSED": "#1B1E27",
    # Текст
    "TEXT": "#F3F4F6",
    "MUTED": "#A1A1AA",
    "DISABLED_TEXT": "#757A8A",
    # Фиолетовый акцент: заливка кнопок, ссылки и выделения
    "ACCENT": "#7C3AED",
    "ACCENT_HOVER": "#8B5CF6",
    "ACCENT_PRESSED": "#6D28D9",
    "ACCENT_DISABLED": "#362163",
    "ACCENT_TEXT": "#A78BFA",
    # Статусы
    "SUCCESS": "#34D399",
    "WARNING": "#FBBF24",
    "DANGER": "#F87171",
    # Боковая панель
    "SIDEBAR": "#181A22",
    "SIDEBAR_TEXT": "#A1A1AA",
    "SIDEBAR_MUTED": "#8B90A0",
    "SIDEBAR_HOVER": "#232632",
    "SIDEBAR_ACTIVE": "#312951",
    "SIDEBAR_ACTIVE_TEXT": "#DDD6FE",
    # Полосы прокрутки
    "SCROLL_HANDLE": "#4A5066",
    "SCROLL_HANDLE_HOVER": "#5A6178",
}

_QSS_TEMPLATE = """
/* ---------- Базовые элементы ---------- */
QLabel {
    color: @TEXT@;
}
QLabel:disabled {
    color: @DISABLED_TEXT@;
}
QDialog {
    background-color: @BACKGROUND@;
}
QToolTip {
    color: @TEXT@;
    background-color: @BUTTON@;
    border: 1px solid @INPUT_BORDER@;
    padding: 4px 8px;
}

/* ---------- Боковая панель ---------- */
#Sidebar {
    background-color: @SIDEBAR@;
    border-right: 1px solid @BORDER@;
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
    color: @TEXT@;
}
QPushButton#NavButton:checked {
    background-color: @SIDEBAR_ACTIVE@;
    color: @SIDEBAR_ACTIVE_TEXT@;
    font-weight: 600;
}

/* ---------- Основная область и текст ---------- */
#ContentArea {
    background-color: @BACKGROUND@;
}
QScrollArea#PageScroll {
    background: transparent;
    border: none;
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
#Muted, #SearchExcerpt {
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
QPushButton {
    background-color: @BUTTON@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-radius: 8px;
    padding: 8px 16px;
}
QPushButton:hover {
    background-color: @BUTTON_HOVER@;
}
QPushButton:pressed {
    background-color: @BUTTON_PRESSED@;
}
QPushButton:focus {
    border: 1px solid @ACCENT_TEXT@;
}
QPushButton:disabled {
    background-color: transparent;
    color: @DISABLED_TEXT@;
    border: 1px solid @BORDER@;
}
QPushButton#PrimaryButton {
    background-color: @ACCENT@;
    color: #FFFFFF;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 9px 17px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: @ACCENT_HOVER@;
}
QPushButton#PrimaryButton:pressed {
    background-color: @ACCENT_PRESSED@;
}
QPushButton#PrimaryButton:focus {
    border: 1px solid @ACCENT_TEXT@;
}
QPushButton#PrimaryButton:disabled {
    background-color: @ACCENT_DISABLED@;
    color: @MUTED@;
    border: 1px solid transparent;
}

/* ---------- Поля ввода ---------- */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: @INPUT_BG@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: @ACCENT@;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid @ACCENT_TEXT@;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {
    background-color: @SURFACE@;
    color: @DISABLED_TEXT@;
    border: 1px solid @BORDER@;
}

/* ---------- Выпадающие списки ---------- */
QComboBox {
    background-color: @INPUT_BG@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-radius: 8px;
    padding: 6px 10px;
}
QComboBox:focus, QComboBox:on {
    border: 1px solid @ACCENT_TEXT@;
}
QComboBox:disabled {
    background-color: @SURFACE@;
    color: @DISABLED_TEXT@;
    border: 1px solid @BORDER@;
}
QComboBox QAbstractItemView {
    background-color: @CARD@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    selection-background-color: @ACCENT@;
    selection-color: #FFFFFF;
    outline: 0;
}

/* ---------- Индикаторы прогресса ---------- */
QProgressBar {
    background-color: @INPUT_BG@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-radius: 7px;
    text-align: center;
    min-height: 14px;
}
QProgressBar::chunk {
    background-color: @ACCENT@;
    border-radius: 6px;
}

/* ---------- Вкладки расшифровки и конспекта ---------- */
QTabWidget::pane {
    border: 1px solid @BORDER@;
    background-color: @BACKGROUND@;
}
QTabBar::tab {
    background-color: @SURFACE@;
    color: @MUTED@;
    padding: 8px 16px;
    border: 1px solid @BORDER@;
}
QTabBar::tab:selected {
    color: @TEXT@;
    background-color: @CARD@;
    border-bottom: 2px solid @ACCENT@;
}

/* ---------- Меню ---------- */
QMenu {
    background-color: @CARD@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: @ACCENT@;
    color: #FFFFFF;
}
QMenu::item:disabled {
    color: @DISABLED_TEXT@;
}
QMenu::separator {
    height: 1px;
    background-color: @BORDER@;
    margin: 4px 8px;
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
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: @SCROLL_HANDLE@;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: @SCROLL_HANDLE_HOVER@;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
"""


def build_stylesheet() -> str:
    """Возвращает готовый текст стилей с подставленными цветами."""
    stylesheet = _QSS_TEMPLATE
    for name, value in COLORS.items():
        stylesheet = stylesheet.replace(f"@{name}@", value)
    return stylesheet
