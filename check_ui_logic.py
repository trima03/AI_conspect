"""Проверка частей интерфейса, которые не зависят от Qt (formatting.py, overview.py).

Запуск из корня проекта:  python check_ui_logic.py
PySide6 для этой проверки не нужен. Используется временная база SQLite,
настоящая папка data/ проекта не меняется.
"""

import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Чтобы не нужно было устанавливать проект, подключаем папку src вручную.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from konspekt import storage  # noqa: E402
from konspekt.ui import formatting, overview  # noqa: E402

failures = 0


def check(condition: bool, description: str) -> None:
    """Печатает OK или FAIL для одной проверки."""
    global failures
    if condition:
        print(f"  OK    {description}")
    else:
        failures += 1
        print(f"  FAIL  {description}")


def snapshot_tree(path: Path):
    """Запоминает состояние папки (имена, размеры, время изменения)."""
    if not path.exists():
        return None
    result = {}
    for item in sorted(path.rglob("*")):
        info = item.stat()
        result[str(item.relative_to(path))] = (info.st_size, info.st_mtime_ns)
    return result


def main() -> None:
    real_data_before = snapshot_tree(PROJECT_ROOT / "data")

    print("1. Модули не зависят от Qt")
    check("PySide6" not in sys.modules, "formatting.py и overview.py не загружают PySide6")

    print("2. Склонение слов")
    lesson_forms = ("лекция", "лекции", "лекций")
    expected = {
        0: "лекций", 1: "лекция", 2: "лекции", 3: "лекции", 4: "лекции", 5: "лекций",
        9: "лекций", 10: "лекций", 11: "лекций", 12: "лекций", 13: "лекций",
        14: "лекций", 15: "лекций", 21: "лекция", 22: "лекции", 25: "лекций",
        101: "лекция", 111: "лекций", 112: "лекций", 121: "лекция",
    }
    wrong = [n for n, word in expected.items() if formatting.plural_ru(n, *lesson_forms) != word]
    check(not wrong, f"числа 0-125 склоняются верно (ошибки: {wrong})")

    print("3. Статусы")
    for status in storage.ALL_STATUSES:
        style = formatting.status_style(status)
        check(
            bool(style.text) and bool(style.hint)
            and re.fullmatch(r"#[0-9A-Fa-f]{6}", style.foreground) is not None
            and re.fullmatch(r"#[0-9A-Fa-f]{6}", style.background) is not None,
            f"статус {status}: есть текст «{style.text}», подсказка и два цвета",
        )
    texts = [formatting.status_style(s).text for s in storage.ALL_STATUSES]
    check(len(set(texts)) == len(texts), "у разных статусов разные подписи")
    check(
        "ещё не запускалась" in formatting.status_style(storage.STATUS_QUEUED).hint,
        "для статуса queued подсказка говорит, что расшифровка не запускалась",
    )
    unknown = formatting.status_style("something_else")
    check(unknown.text == "Неизвестно", "незнакомый статус не ломает отображение")

    print("4. Приветствие")
    greetings = {hour: formatting.greeting_for_hour(hour) for hour in range(24)}
    check(
        greetings[5] == "Доброе утро" and greetings[11] == "Доброе утро",
        "5-11 часов: доброе утро",
    )
    check(
        greetings[12] == "Добрый день" and greetings[17] == "Добрый день",
        "12-17 часов: добрый день",
    )
    check(
        greetings[18] == "Добрый вечер" and greetings[22] == "Добрый вечер",
        "18-22 часа: добрый вечер",
    )
    check(
        greetings[23] == "Доброй ночи" and greetings[0] == "Доброй ночи" and greetings[4] == "Доброй ночи",
        "23-4 часа: доброй ночи",
    )

    print("5. Даты и тексты")
    check(formatting.format_datetime(None) == "—", "нет даты: тире")
    check(formatting.format_datetime("") == "—", "пустая дата: тире")
    check(
        formatting.format_datetime("2026-10-12T14:05:00") == "12.10.2026 14:05",
        "дата без часового пояса показывается как есть",
    )
    local = formatting.format_datetime("2026-10-12T14:05:00+00:00")
    check(
        re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", local) is not None,
        f"дата в UTC переводится в формат ДД.ММ.ГГГГ ЧЧ:ММ ({local})",
    )
    check(formatting.format_datetime("не дата") == "не дата", "непонятный текст не ломает показ")
    check(formatting.shorten("  много   пробелов \n тут ") == "много пробелов тут", "лишние пробелы убираются")
    long_text = "а" * 300
    shortened = formatting.shorten(long_text, 50)
    check(len(shortened) == 50 and shortened.endswith("…"), "длинный текст обрезается многоточием")
    check(formatting.shorten("коротко", 50) == "коротко", "короткий текст не меняется")

    with tempfile.TemporaryDirectory(prefix="konspekt_ui_logic_check_") as temp_dir:
        temp_path = Path(temp_dir).resolve()
        os.environ[storage.DATA_DIR_ENV_VAR] = str(temp_path / "data")

        print("6. Безопасность проверки")
        check(
            temp_path in storage.get_db_path().parents,
            "база для проверки лежит во временной папке",
        )

        print("7. Главная страница: данные из хранилища")
        check(
            raised_storage_error(overview.load_overview),
            "до создания базы выдаётся понятная StorageError, а не падение",
        )
        storage.init_db()
        empty = overview.load_overview()
        check(
            empty.subject_count == 0 and empty.lesson_count == 0 and empty.recent == (),
            "пустая база: 0 предметов, 0 лекций, список пуст",
        )

        physics = storage.create_subject("Физика")
        math_subject = storage.create_subject("Математика")
        history = storage.create_subject("История")  # без лекций
        only_subjects = overview.load_overview()
        check(
            only_subjects.subject_count == 3 and only_subjects.lesson_count == 0,
            "предметы без лекций: 3 предмета, 0 лекций",
        )

        created = []
        for number in range(1, 8):
            subject = physics if number % 2 else math_subject
            created.append(storage.create_lesson(subject.id, f"Лекция {number}", f"a{number}.mp3"))
        storage.set_lesson_status(created[2].id, storage.STATUS_FAILED, "Нет подключения к интернету")
        storage.set_lesson_status(created[5].id, storage.STATUS_COMPLETED)

        data = overview.load_overview()
        check(data.subject_count == 3, "счётчик предметов: 3")
        check(data.lesson_count == 7, "счётчик лекций: 7 (из разных предметов)")
        check(len(data.recent) == 5, "в последних лекциях по умолчанию 5 записей")
        check(
            [item.title for item in data.recent]
            == ["Лекция 7", "Лекция 6", "Лекция 5", "Лекция 4", "Лекция 3"],
            "последние лекции идут от новых к старым",
        )
        check(
            data.recent[0].subject_name == "Физика" and data.recent[1].subject_name == "Математика",
            "у лекций верные названия предметов",
        )
        check(
            data.recent[1].status == storage.STATUS_COMPLETED and data.recent[0].status == storage.STATUS_QUEUED,
            "статусы лекций переданы верно",
        )
        failed_item = data.recent[4]
        check(
            failed_item.status == storage.STATUS_FAILED
            and failed_item.error_message == "Нет подключения к интернету",
            "у лекции с ошибкой передан текст ошибки",
        )
        check(
            len(overview.load_overview(limit=2).recent) == 2
            and len(overview.load_overview(limit=50).recent) == 7,
            "параметр limit работает (меньше и больше числа лекций)",
        )
        check(
            overview.load_overview(limit=0).recent == (),
            "limit=0 даёт пустой список",
        )
        check(
            all(item.id > 0 and item.created_at for item in data.recent),
            "у каждой записи есть номер и дата создания",
        )
        check(history.id > 0, "предмет без лекций не мешает подсчёту")

        print("8. Хранилище не изменилось от чтения")
        again = overview.load_overview()
        check(again == data, "повторное чтение даёт тот же результат")
        check(
            [lesson.status for lesson in storage.list_lessons(physics.id)].count(storage.STATUS_FAILED) == 1,
            "данные в базе не менялись",
        )

    print("9. Настоящие данные проекта")
    check(
        snapshot_tree(PROJECT_ROOT / "data") == real_data_before,
        "папка data/ проекта не создана и не изменена",
    )

    print()
    if failures:
        print(f"ИТОГ: проверок не пройдено: {failures}")
        sys.exit(1)
    print("ИТОГ: все проверки пройдены.")


def raised_storage_error(function) -> bool:
    """True, если функция выдала storage.StorageError."""
    try:
        function()
    except storage.StorageError as error:
        return bool(re.search(r"[А-Яа-яЁё]", str(error)))
    except Exception as error:
        print(f"        (получена другая ошибка: {type(error).__name__}: {error})")
        return False
    return False


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Непредвиденная ошибка внутри проверки: показываем её и считаем проверку проваленной.
        traceback.print_exc()
        print()
        print("ИТОГ: проверка прервана из-за непредвиденной ошибки (см. выше).")
        sys.exit(1)
