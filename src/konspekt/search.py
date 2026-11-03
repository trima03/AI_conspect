"""Search the local library without changing its schema or indexing private text."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from . import storage

MAX_QUERY_CHARS = 200
RESULT_LIMIT = 100


@dataclass(frozen=True)
class LessonMatch:
    lesson: storage.Lesson
    subject_name: str
    excerpt: str


@dataclass(frozen=True)
class SearchResults:
    matches: tuple[LessonMatch, ...]
    total: int


def _normalize(text: str | None) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold().replace("ё", "е")


def _excerpt(lesson: storage.Lesson, subject_name: str, terms: list[str]) -> str:
    if not terms:
        return ""
    fields = [("Конспект", lesson.summary), ("Расшифровка", lesson.transcript),
              ("Название", lesson.title), ("Предмет", subject_name)]
    for label, value in fields:
        if not value:
            continue
        clean = " ".join(value.split())
        for word in re.finditer(r"\S+", clean):
            if not any(term in _normalize(word.group()) for term in terms):
                continue
            start = max(0, word.start() - 70)
            if start:
                boundary = clean.find(" ", start, word.start())
                if boundary >= 0:
                    start = boundary + 1
            end = min(len(clean), max(word.end(), start + 220))
            if end < len(clean):
                boundary = clean.rfind(" ", word.end(), end)
                if boundary >= word.end():
                    end = boundary
            return f"{label}: {'…' if start else ''}{clean[start:end]}{'…' if end < len(clean) else ''}"
    return ""


def search_lessons(query: str = "", *, subject_id: int | None = None,
                   status: str | None = None) -> SearchResults:
    """All words must appear, possibly in different fields; symbols stay literal."""
    if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"Поисковый запрос должен быть строкой до {MAX_QUERY_CHARS} символов.")
    if status is not None and status not in storage.ALL_STATUSES:
        raise ValueError("Неизвестное состояние обработки.")
    terms = list(dict.fromkeys(_normalize(query).split()))
    conditions = ["l.deleted_at IS NULL"]
    parameters: list[str | int] = []
    if subject_id is not None:
        conditions.append("l.subject_id = ?")
        parameters.append(subject_id)
    if status is not None:
        conditions.append("l.status = ?")
        parameters.append(status)
    for term in terms:
        conditions.append("""(instr(search_text(l.title), ?) > 0
            OR instr(search_text(s.name), ?) > 0
            OR instr(search_text(l.transcript), ?) > 0
            OR instr(search_text(l.summary), ?) > 0)""")
        parameters.extend([term] * 4)
    where = " AND ".join(conditions)
    with storage._connect() as conn:
        conn.create_function("search_text", 1, _normalize, deterministic=True)
        rows = conn.execute(
            f"""SELECT l.*, s.name AS subject_name, COUNT(*) OVER () AS match_count
                FROM lessons AS l JOIN subjects AS s ON s.id = l.subject_id
                WHERE {where} ORDER BY l.id DESC LIMIT ?""",
            [*parameters, RESULT_LIMIT],
        ).fetchall()
    matches = []
    for row in rows:
        lesson = storage._to_lesson(row)
        matches.append(LessonMatch(lesson, row["subject_name"], _excerpt(lesson, row["subject_name"], terms)))
    return SearchResults(tuple(matches), rows[0]["match_count"] if rows else 0)
