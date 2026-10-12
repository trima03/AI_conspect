"""Связь аудиофайлов с уроками: файлы на диске + записи в SQLite.

Две функции:

    create_lesson_with_audio(subject_id, title, source_path)
        создаёт НОВЫЙ урок сразу с аудио одной операцией;

    attach_audio_to_lesson(lesson_id, source_path)
        привязывает аудио к УЖЕ существующему уроку.

В обеих функциях порядок один: сначала всё проверяется, потом создаётся копия
аудио в data/audio/ и только потом пишется запись в базу. Если запись в базу
не удалась, только что созданная копия удаляется.

Исходный файл не изменяется и не удаляется. Модуль не обращается к интернету
и не запускает распознавание речи.

Пример:
    from konspekt import audio, lesson_audio, storage

    try:
        lesson = lesson_audio.create_lesson_with_audio(
            1, "Законы Ньютона", "C:/Users/me/lesson.mp3"
        )
    except (audio.AudioError, storage.StorageError, ValueError) as error:
        print(error)  # понятное сообщение на русском

Код совместим с Python 3.10 и новее, сторонние библиотеки не нужны.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from . import audio, storage


def _remove_copy(copy_path: Path) -> bool:
    """Удаляет только что созданную копию. Возвращает True, если её больше нет.

    Удаляется один конкретный файл, и только если он лежит прямо в папке
    data/audio/. Исходный файл пользователя сюда попасть не может: копия
    всегда новый файл с новым именем.
    """
    try:
        if copy_path.parent.resolve() != storage.get_audio_dir().resolve():
            return False
        if copy_path.is_file():
            copy_path.unlink()
        return True
    except OSError:
        return False


def _cleanup_after_failed_write(error: BaseException, copy_path: Path) -> None:
    """Вызывается, когда запись в базу не удалась, а копия аудио уже создана.

    Удаляет копию. Если причина сбоя ошибка SQLite, превращает её в понятную
    StorageError (и сообщает, удалась ли уборка). Для любых других ошибок
    ничего не выбрасывает: вызывающая функция сама пробросит исходную ошибку.
    """
    removed = _remove_copy(copy_path)
    if isinstance(error, sqlite3.Error):
        if removed:
            tail = "Созданная копия аудио удалена."
        else:
            tail = (
                f"Не удалось удалить копию «{copy_path.name}», "
                "она осталась в папке аудио."
            )
        raise storage.StorageError(
            f"Не удалось сохранить урок в базе данных: {error}. {tail}"
        ) from error


def create_lesson_with_audio(
    subject_id: int, title: str, source_path: str | os.PathLike[str]
) -> storage.Lesson:
    """Создаёт урок с аудио одной операцией и возвращает созданный урок.

    Порядок действий:
        1. проверяется предмет;
        2. проверяется название урока;
        3. проверяется аудиофайл и делается его копия в data/audio/;
        4. в базе создаётся урок со статусом queued и путём к копии.

    Возможные ошибки (все с текстом на русском):
        storage.NotFoundError            предмета с таким номером нет;
        ValueError                       название урока пустое;
        audio.AudioError и его виды      файл не подходит (нет файла, формат,
                                         размер) или копирование не удалось;
        storage.StorageError             не удалось сохранить урок в базе.

    Урок записывается в базу только после того, как копия аудио полностью
    создана. Поэтому записи об уроке без аудиофайла появиться не может.
    Если запись в базу не удалась, копия удаляется.
    """
    # 1. Предмет должен существовать (NotFoundError, если нет).
    storage.get_subject(subject_id)

    # 2. Название проверяем ДО копирования, чтобы не копировать файл зря.
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Название урока не может быть пустым.")

    # 3. Копия аудио (здесь же проверяются существование, формат и размер).
    copy_path = audio.save_audio(source_path)

    # 4. Запись урока в базу. При любом сбое убираем созданную копию.
    try:
        return storage.create_lesson(subject_id, title, copy_path)
    except BaseException as error:
        _cleanup_after_failed_write(error, copy_path)
        raise


def attach_audio_to_lesson(
    lesson_id: int, source_path: str | os.PathLike[str]
) -> storage.Lesson:
    """Сохраняет копию аудио и записывает путь к ней в урок.

    Возвращает обновлённый урок. Возможные ошибки (все с текстом на русском):
        storage.NotFoundError            урока с таким номером нет;
        audio.AudioError и его виды      исходный файл не подходит (нет файла,
                                         формат, размер) или копирование не удалось;
        storage.StorageError             не удалось записать путь в базу.

    Если у урока уже был аудиофайл, старый файл НЕ удаляется:
    в урок записывается путь к новой копии.
    """
    # 1. Урок должен существовать до того, как мы создадим хоть какой-то файл.
    storage.get_lesson(lesson_id)

    # 2. Копия аудио (здесь же проверяются формат и размер).
    copy_path = audio.save_audio(source_path)

    # 3. Запись пути в базу. При любом сбое убираем созданную копию.
    try:
        return storage.set_lesson_audio_path(lesson_id, copy_path)
    except BaseException as error:
        removed = _remove_copy(copy_path)
        if isinstance(error, sqlite3.Error):
            if removed:
                tail = "Созданная копия аудио удалена."
            else:
                tail = (
                    f"Не удалось удалить копию «{copy_path.name}», "
                    "она осталась в папке аудио."
                )
            raise storage.StorageError(
                f"Не удалось сохранить путь к аудио в базе данных: {error}. {tail}"
            ) from error
        raise