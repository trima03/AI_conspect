"""Проверка storage.py на ВРЕМЕННОЙ базе данных.

Запуск из корня проекта:  python check_storage.py
Настоящая база (data/konspekt.db) не используется и не меняется.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Чтобы не нужно было устанавливать проект, подключаем папку src вручную.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from konspekt import storage  # noqa: E402

failures = 0


def check(condition: bool, description: str) -> None:
    """Печатает OK или FAIL для одной проверки."""
    global failures
    if condition:
        print(f"  OK    {description}")
    else:
        failures += 1
        print(f"  FAIL  {description}")


def raises(error_type: type, function, *args) -> bool:
    """True, если функция выдала ошибку нужного типа."""
    try:
        function(*args)
    except error_type:
        return True
    except Exception as error:  # ошибка другого типа
        print(f"        (получена другая ошибка: {type(error).__name__}: {error})")
        return False
    return False


def snapshot(path: Path):
    """Запоминает состояние файла, чтобы потом убедиться, что он не изменился."""
    if not path.exists():
        return None
    info = path.stat()
    return (info.st_size, info.st_mtime_ns)


def main() -> None:
    real_db = PROJECT_ROOT / "data" / "konspekt.db"
    real_db_before = snapshot(real_db)

    with tempfile.TemporaryDirectory(prefix="konspekt_check_") as temp_dir:
        # Направляем storage.py во временную папку.
        os.environ[storage.DATA_DIR_ENV_VAR] = temp_dir
        temp_path = Path(temp_dir).resolve()

        print("1. Безопасность проверки")
        check(
            temp_path in storage.get_db_path().parents,
            "база для проверки лежит во временной папке",
        )
        check(
            storage.get_db_path() != real_db,
            "это не настоящая база проекта",
        )

        print("2. Создание базы")
        check(
            raises(storage.StorageError, storage.list_subjects),
            "до init_db() понятная ошибка вместо падения",
        )
        storage.init_db()
        check(storage.get_db_path().is_file(), "файл базы создан")
        check(storage.get_audio_dir().is_dir(), "папка audio создана")
        storage.init_db()
        check(True, "повторный init_db() не ломает базу")
        check(storage.list_subjects() == [], "в новой базе нет предметов")

        print("3. Предметы")
        physics = storage.create_subject("  Физика  ")
        check(physics.name == "Физика", "пробелы по краям убираются")
        check(physics.id > 0, "предмету присвоен номер")
        math_subject = storage.create_subject("Математика")
        check(
            [s.name for s in storage.list_subjects()] == ["Физика", "Математика"],
            "список предметов в порядке создания",
        )
        check(storage.get_subject(physics.id) == physics, "get_subject находит предмет")
        check(
            raises(storage.DuplicateSubjectError, storage.create_subject, "физика"),
            "дубликат «физика» (другой регистр) запрещён",
        )
        check(
            raises(storage.DuplicateSubjectError, storage.create_subject, " ФИЗИКА "),
            "дубликат « ФИЗИКА » (регистр и пробелы) запрещён",
        )
        check(
            raises(storage.DuplicateSubjectError, storage.create_subject, "Физика"),
            "точный дубликат запрещён",
        )
        check(len(storage.list_subjects()) == 2, "дубликаты не попали в базу")
        check(raises(ValueError, storage.create_subject, ""), "пустое название запрещено")
        check(raises(ValueError, storage.create_subject, "   "), "название из пробелов запрещено")
        check(raises(storage.NotFoundError, storage.get_subject, 9999), "нет предмета: NotFoundError")

        print("4. Уроки")
        lesson1 = storage.create_lesson(physics.id, "  Законы Ньютона ", "data/audio/1.mp3")
        check(lesson1.title == "Законы Ньютона", "пробелы в названии урока убираются")
        check(lesson1.status == storage.STATUS_QUEUED, "новый урок получает статус queued")
        check(
            lesson1.transcript is None and lesson1.summary is None,
            "текст и конспект пока пустые",
        )
        check(lesson1.error_message is None, "ошибки нет")
        lesson2 = storage.create_lesson(physics.id, "Энергия", Path("data/audio/2.mp3"))
        check(lesson2.audio_path.endswith("2.mp3"), "путь можно передать как Path")
        lesson3 = storage.create_lesson(math_subject.id, "Интегралы", "data/audio/3.mp3")
        check(
            [x.title for x in storage.list_lessons(physics.id)]
            == ["Законы Ньютона", "Энергия"],
            "уроки физики: только свои, в порядке создания",
        )
        check(
            [x.title for x in storage.list_lessons(math_subject.id)] == ["Интегралы"],
            "уроки математики не смешиваются с физикой",
        )
        check(storage.list_lessons(9999) == [], "у неизвестного предмета список пуст")
        check(storage.get_lesson(lesson1.id) == lesson1, "get_lesson находит урок")
        check(raises(storage.NotFoundError, storage.get_lesson, 9999), "нет урока: NotFoundError")
        check(
            raises(storage.NotFoundError, storage.create_lesson, 9999, "Тест", "a.mp3"),
            "урок для несуществующего предмета запрещён",
        )
        check(raises(ValueError, storage.create_lesson, physics.id, " ", "a.mp3"), "пустое название урока запрещено")
        check(raises(ValueError, storage.create_lesson, physics.id, "Тест", ""), "пустой путь к аудио запрещён")

        print("5. Статусы")
        updated = storage.set_lesson_status(lesson1.id, storage.STATUS_PROCESSING)
        check(updated.status == "processing", "queued -> processing")
        check(storage.get_lesson(lesson1.id).status == "processing", "статус сохранился в базе")
        check(updated.updated_at >= lesson1.updated_at, "updated_at не стал раньше")
        updated = storage.set_lesson_status(lesson1.id, storage.STATUS_FAILED, "Нет сети")
        check(
            updated.status == "failed" and updated.error_message == "Нет сети",
            "processing -> failed с текстом ошибки",
        )
        updated = storage.set_lesson_status(lesson1.id, storage.STATUS_QUEUED)
        check(
            updated.status == "queued" and updated.error_message is None,
            "повтор: failed -> queued стирает старую ошибку",
        )
        updated = storage.set_lesson_status(
            lesson1.id, storage.STATUS_COMPLETED, "эта ошибка не должна сохраниться"
        )
        check(
            updated.status == "completed" and updated.error_message is None,
            "ошибка сохраняется только для failed",
        )
        check(
            storage.get_lesson(lesson2.id).status == "queued",
            "статус другого урока не изменился",
        )
        check(raises(ValueError, storage.set_lesson_status, lesson1.id, "done"), "неверный статус отвергается")
        check(storage.get_lesson(lesson1.id).status == "completed", "после неверного статуса данные целы")
        check(
            raises(storage.NotFoundError, storage.set_lesson_status, 9999, "queued"),
            "статус несуществующего урока: NotFoundError",
        )

        print("6. Защита на уровне самой базы")
        conn = sqlite3.connect(storage.get_db_path())
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            check(
                raises(
                    sqlite3.IntegrityError,
                    conn.execute,
                    "INSERT INTO lessons (subject_id, title, audio_path, status, created_at, updated_at) "
                    "VALUES (?, 't', 'p', 'wrong', 'x', 'x')",
                    (physics.id,),
                ),
                "база сама отвергает неверный статус",
            )
            check(
                raises(
                    sqlite3.IntegrityError,
                    conn.execute,
                    "INSERT INTO lessons (subject_id, title, audio_path, status, created_at, updated_at) "
                    "VALUES (9999, 't', 'p', 'queued', 'x', 'x')",
                    (),
                ),
                "база сама отвергает урок без существующего предмета",
            )
        finally:
            conn.close()

        print("7. Данные сохраняются между обращениями")
        check(
            [s.name for s in storage.list_subjects()] == ["Физика", "Математика"]
            and len(storage.list_lessons(physics.id)) == 2
            and storage.get_lesson(lesson3.id).title == "Интегралы",
            "данные читаются заново из файла базы",
        )

    print("8. Настоящие данные проекта")
    check(
        snapshot(real_db) == real_db_before,
        "файл data/konspekt.db не создан и не изменён",
    )

    print()
    if failures:
        print(f"ИТОГ: проверок не пройдено: {failures}")
        sys.exit(1)
    print("ИТОГ: все проверки пройдены.")


if __name__ == "__main__":
    main()
