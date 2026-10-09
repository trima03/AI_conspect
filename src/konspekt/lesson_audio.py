"""Привязка аудиофайла к существующему уроку.

Что делает модуль (функция attach_audio_to_lesson):
    1. проверяет, что урок есть в базе;
    2. копирует аудио в data/audio/ через audio.save_audio();
    3. записывает путь к копии в урок (в SQLite);
    4. если запись в базу не удалась, удаляет только что созданную копию.

Исходный файл не изменяется и не удаляется. Модуль не обращается к интернету
и не запускает распознавание речи. Остальные поля урока (статус, текст,
конспект, ошибка) не меняются.

Пример:
    from konspekt import lesson_audio, storage

    try:
        lesson = lesson_audio.attach_audio_to_lesson(5, "C:/Users/me/lesson.mp3")
    except (audio.AudioError, storage.StorageError) as error:
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
