"""Данные для главной страницы: счётчики и последние лекции.

Здесь нет ничего от Qt. Всё берётся из существующего storage.py,
никакого собственного SQL.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import storage


@dataclass(frozen=True)
class RecentLesson:
    id: int
    title: str
    subject_name: str
    created_at: str
    status: str
    error_message: str | None


@dataclass(frozen=True)
class Overview:
    subject_count: int
    lesson_count: int
    recent: tuple[RecentLesson, ...]


def load_overview(limit: int = 5) -> Overview:
    """Считает предметы и лекции и выбирает несколько самых новых лекций.

    Может выдать storage.StorageError (например, если база не создана).
    """
    subjects = storage.list_subjects()
    names = {subject.id: subject.name for subject in subjects}

    lessons = []
    for subject in subjects:
        lessons.extend(storage.list_lessons(subject.id))

    # Чем позже создана лекция, тем больше её номер (id), поэтому сортируем по нему:
    # дата в базе хранится с точностью до секунды, а номера никогда не повторяются.
    lessons.sort(key=lambda lesson: lesson.id, reverse=True)

    recent = tuple(
        RecentLesson(
            id=lesson.id,
            title=lesson.title,
            subject_name=names.get(lesson.subject_id, "—"),
            created_at=lesson.created_at,
            status=lesson.status,
            error_message=lesson.error_message,
        )
        for lesson in lessons[:limit]
    )
    return Overview(
        subject_count=len(subjects),
        lesson_count=len(lessons),
        recent=recent,
    )
