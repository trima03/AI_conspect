"""Текст и оформление для интерфейса: статусы, даты, склонение слов.

В этом модуле нет ничего от Qt, поэтому его можно проверять без PySide6
(см. check_ui_logic.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import storage


@dataclass(frozen=True)
class StatusStyle:
    """Как показывать статус лекции."""

    text: str        # короткий текст на значке
    hint: str        # подсказка при наведении мыши
    foreground: str  # цвет текста значка
    background: str  # цвет фона значка


_STATUS_STYLES = {
    storage.STATUS_QUEUED: StatusStyle(
        "В очереди",
        "Расшифровка ещё не запускалась.",
        "#475569",
        "#E2E8F0",
    ),
    storage.STATUS_PROCESSING: StatusStyle(
        "Обрабатывается",
        "Идёт распознавание аудио или создание конспекта.",
        "#1D4ED8",
        "#DBEAFE",
    ),
    storage.STATUS_COMPLETED: StatusStyle(
        "Готово",
        "Расшифровка готова. Конспект доступен на отдельной вкладке после создания.",
        "#047857",
        "#D1FAE5",
    ),
    storage.STATUS_FAILED: StatusStyle(
        "Ошибка",
        "Обработка завершилась ошибкой.",
        "#B91C1C",
        "#FEE2E2",
    ),
}

_UNKNOWN_STATUS = StatusStyle(
    "Неизвестно", "Неизвестный статус обработки.", "#475569", "#E2E8F0"
)


def status_style(status: str) -> StatusStyle:
    """Оформление для статуса. Для незнакомого статуса возвращает запасное."""
    return _STATUS_STYLES.get(status, _UNKNOWN_STATUS)


def plural_ru(number: int, one: str, few: str, many: str) -> str:
    """Правильная форма слова: 1 лекция, 2 лекции, 5 лекций."""
    number = abs(number)
    if 11 <= number % 100 <= 14:
        return many
    last_digit = number % 10
    if last_digit == 1:
        return one
    if 2 <= last_digit <= 4:
        return few
    return many


def greeting_for_hour(hour: int) -> str:
    """Приветствие по времени суток (hour: 0-23)."""
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    if 18 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


def format_datetime(iso_text: str | None) -> str:
    """Дата из базы (UTC, ISO-текст) в местном времени: 12.10.2026 14:05."""
    if not iso_text:
        return "—"
    try:
        moment = datetime.fromisoformat(iso_text)
    except ValueError:
        return iso_text
    if moment.tzinfo is not None:
        moment = moment.astimezone()  # перевод в часовой пояс компьютера
    return moment.strftime("%d.%m.%Y %H:%M")


def shorten(text: str, limit: int = 140) -> str:
    """Сжимает пробелы и обрезает длинный текст многоточием."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
