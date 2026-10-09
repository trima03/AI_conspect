"""Проверка привязки аудио к уроку (lesson_audio.py) на ВРЕМЕННЫХ данных.

Запуск из корня проекта:  python check_lesson_audio.py
Используются временная папка и временная база SQLite. Настоящая папка data/
проекта не меняется. Тестовые файлы создаются сами и удаляются в конце.
"""

import ast
import dataclasses
import hashlib
import os
import pathlib
import re
import sqlite3
import sys
import tempfile
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Чтобы не нужно было устанавливать проект, подключаем папку src вручную.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from konspekt import audio, lesson_audio, storage  # noqa: E402

failures = 0


def check(condition: bool, description: str) -> None:
    """Печатает OK или FAIL для одной проверки."""
    global failures
    if condition:
        print(f"  OK    {description}")
    else:
        failures += 1
        print(f"  FAIL  {description}")


def raised(error_type: type, function, *args):
    """Возвращает ошибку нужного типа, если функция её выдала, иначе None."""
    try:
        function(*args)
    except error_type as error:
        return error
    except Exception as error:  # ошибка другого типа
        print(f"        (получена другая ошибка: {type(error).__name__}: {error})")
        return None
    return None


def is_russian(error) -> bool:
    """True, если в тексте ошибки есть русские буквы."""
    return error is not None and re.search(r"[А-Яа-яЁё]", str(error)) is not None


def make_file(folder: Path, name: str, content: bytes) -> Path:
    path = folder / name
    path.write_bytes(content)
    return path


def make_sized_file(folder: Path, name: str, size: int) -> Path:
    """Создаёт файл точно нужного размера (содержимое — нули)."""
    path = folder / name
    with open(path, "wb") as file:
        file.truncate(size)
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_names(folder: Path) -> list:
    return sorted(item.name for item in folder.iterdir())


def snapshot_tree(path: Path):
    """Запоминает состояние папки (имена, размеры, время изменения)."""
    if not path.exists():
        return None
    result = {}
    for item in sorted(path.rglob("*")):
        info = item.stat()
        result[str(item.relative_to(path))] = (info.st_size, info.st_mtime_ns)
    return result


def set_text_fields(lesson_id: int, transcript: str, summary: str) -> None:
    """Записывает текст и конспект напрямую в базу (в storage.py такой функции пока нет)."""
    conn = sqlite3.connect(storage.get_db_path())
    try:
        with conn:
            conn.execute(
                "UPDATE lessons SET transcript = ?, summary = ? WHERE id = ?",
                (transcript, summary, lesson_id),
            )
    finally:
        conn.close()


def fields_except(lesson, *skipped: str) -> dict:
    """Все поля урока в виде словаря, кроме перечисленных."""
    data = dataclasses.asdict(lesson)
    for name in skipped:
        data.pop(name)
    return data


def main() -> None:
    real_data_before = snapshot_tree(PROJECT_ROOT / "data")

    with tempfile.TemporaryDirectory(prefix="konspekt_lesson_audio_check_") as temp_dir:
        temp_path = Path(temp_dir).resolve()
        data_dir = temp_path / "data"
        source_dir = temp_path / "source"
        source_dir.mkdir()

        # Направляем storage.py (а значит, audio.py и lesson_audio.py) во временную папку.
        os.environ[storage.DATA_DIR_ENV_VAR] = str(data_dir)
        storage.init_db()
        audio_dir = storage.get_audio_dir()

        print("1. Безопасность проверки")
        check(
            temp_path in storage.get_db_path().parents,
            "база для проверки лежит во временной папке",
        )
        check(
            temp_path in audio_dir.parents,
            "папка для копий лежит во временной папке",
        )
        check(
            storage.get_db_path() != PROJECT_ROOT / "data" / "konspekt.db",
            "это не настоящая база проекта",
        )

        # --- Подготовка тестовых данных -----------------------------------
        physics = storage.create_subject("Физика")
        math_subject = storage.create_subject("Математика")
        service_subject = storage.create_subject("Служебный")

        lesson = storage.create_lesson(physics.id, "Законы Ньютона", "pending/old_placeholder.mp3")
        neighbour_same = storage.create_lesson(physics.id, "Энергия", "pending/other.mp3")
        neighbour_other = storage.create_lesson(math_subject.id, "Интегралы", "pending/third.mp3")
        probe = storage.create_lesson(service_subject.id, "Проверочный", "pending/probe.mp3")

        # У проверяемого урока заполняем все поля, чтобы увидеть, не пропадёт ли что-то.
        storage.set_lesson_status(lesson.id, storage.STATUS_FAILED, "Нет сети")
        set_text_fields(lesson.id, "Распознанный текст урока", "Готовый конспект урока")
        lesson_before = storage.get_lesson(lesson.id)
        neighbours_before = [
            storage.get_lesson(neighbour_same.id),
            storage.get_lesson(neighbour_other.id),
        ]

        print("2. Новая функция storage.set_lesson_audio_path")
        probe_before = storage.get_lesson(probe.id)
        changed = storage.set_lesson_audio_path(probe.id, "new/path.mp3")
        check(changed.audio_path == "new/path.mp3", "путь меняется")
        check(storage.get_lesson(probe.id) == changed, "изменение сохранено в базе")
        check(
            fields_except(changed, "audio_path", "updated_at")
            == fields_except(probe_before, "audio_path", "updated_at"),
            "кроме пути и updated_at другие поля не изменились",
        )
        check(changed.updated_at >= probe_before.updated_at, "updated_at не стал раньше")
        check(
            storage.set_lesson_audio_path(probe.id, Path("via") / "path.mp3").audio_path
            == str(Path("via") / "path.mp3"),
            "путь можно передать как Path",
        )
        check(
            raised(ValueError, storage.set_lesson_audio_path, probe.id, "   ") is not None,
            "пустой путь отклоняется",
        )
        check(
            storage.get_lesson(probe.id).audio_path == str(Path("via") / "path.mp3"),
            "после отклонённого пути данные целы",
        )
        error = raised(storage.NotFoundError, storage.set_lesson_audio_path, 9999, "a.mp3")
        check(is_russian(error), "несуществующий урок: NotFoundError, сообщение на русском")

        print("3. Успешная привязка аудио к существующему уроку")
        content = os.urandom(3 * 1024 * 1024 + 5)  # больше одного куска копирования
        source = make_file(source_dir, "lesson_newton.mp3", content)
        source_hash = sha256(source)
        source_info = source.stat()
        audio_names_before = file_names(audio_dir)

        result = lesson_audio.attach_audio_to_lesson(lesson.id, source)
        stored = storage.get_lesson(lesson.id)
        saved = Path(result.audio_path)
        new_files = sorted(set(file_names(audio_dir)) - set(audio_names_before))

        check(isinstance(result, storage.Lesson), "функция возвращает обновлённый урок")
        check(result == stored, "возвращённый урок совпадает с записью в базе")
        check(
            stored.audio_path != lesson_before.audio_path,
            "путь в базе изменился на путь к копии",
        )
        check(saved.is_file(), "сохранённый путь указывает на существующий файл")
        check(saved.parent == audio_dir, "копия лежит в папке data/audio")
        check(saved.suffix == ".mp3", "у копии то же расширение")
        check(len(new_files) == 1 and new_files[0] == saved.name, "в папке audio появилась ровно одна копия")
        check(sha256(saved) == source_hash, "содержимое копии совпадает с оригиналом байт в байт")
        check(saved.stat().st_size == len(content), "размер копии совпадает с оригиналом")
        check(source.is_file(), "оригинал остался на месте")
        check(sha256(source) == source_hash, "содержимое оригинала не изменилось")
        check(
            source.stat().st_size == source_info.st_size
            and source.stat().st_mtime_ns == source_info.st_mtime_ns,
            "размер и время изменения оригинала не изменились",
        )
        check(saved != source, "копия и оригинал — разные файлы")
        check(
            file_names(source_dir) == ["lesson_newton.mp3"],
            "в папке с оригиналом ничего не добавилось и не пропало",
        )

        print("4. Другие поля урока не теряются и не меняются")
        check(stored.status == storage.STATUS_FAILED, "статус не изменился")
        check(stored.error_message == "Нет сети", "текст ошибки не изменился")
        check(stored.transcript == "Распознанный текст урока", "распознанный текст сохранился")
        check(stored.summary == "Готовый конспект урока", "конспект сохранился")
        check(
            fields_except(stored, "audio_path", "updated_at")
            == fields_except(lesson_before, "audio_path", "updated_at"),
            "название, предмет, статус, тексты и дата создания совпадают с прежними",
        )
        check(stored.updated_at >= lesson_before.updated_at, "updated_at не стал раньше")
        check(
            [storage.get_lesson(neighbour_same.id), storage.get_lesson(neighbour_other.id)]
            == neighbours_before,
            "соседние уроки не затронуты",
        )

        print("5. Несуществующий урок: файл не копируется")
        names_before = file_names(audio_dir)
        for bad_id in (9999, 0, -1, None):
            error = raised(storage.NotFoundError, lesson_audio.attach_audio_to_lesson, bad_id, source)
            check(is_russian(error), f"урок {bad_id!r}: NotFoundError, сообщение на русском")
        check(file_names(audio_dir) == names_before, "в папке audio не появилось ни одной копии")
        check(source.is_file() and sha256(source) == source_hash, "оригинал цел")

        print("6. Недопустимые файлы")
        lesson_now = storage.get_lesson(lesson.id)
        names_before = file_names(audio_dir)
        wrong_format = make_file(source_dir, "notes.txt", b"not audio")
        too_big = make_sized_file(source_dir, "too_big.wav", audio.MAX_SIZE_BYTES + 1)
        empty = make_file(source_dir, "empty.mp3", b"")
        cases = [
            ("формат .txt", audio.UnsupportedAudioFormatError, wrong_format),
            ("размер больше 25 МБ", audio.AudioTooLargeError, too_big),
            ("файла нет", audio.AudioFileNotFoundError, source_dir / "missing.mp3"),
            ("пустой файл", audio.AudioError, empty),
        ]
        for label, error_type, bad_source in cases:
            error = raised(error_type, lesson_audio.attach_audio_to_lesson, lesson.id, bad_source)
            check(is_russian(error), f"{label}: отклонён, сообщение на русском")
            check(
                storage.get_lesson(lesson.id) == lesson_now,
                f"{label}: запись урока не изменилась",
            )
            check(file_names(audio_dir) == names_before, f"{label}: копия не создана")
        check(wrong_format.is_file() and too_big.is_file(), "отклонённые исходные файлы на месте")

        print("7. Ошибка базы данных после копирования")
        lesson_now = storage.get_lesson(lesson.id)
        names_before = file_names(audio_dir)
        db_source = make_file(source_dir, "for_db_failure.ogg", os.urandom(4096))
        db_source_hash = sha256(db_source)
        real_set_path = storage.set_lesson_audio_path

        def failing(error):
            def fake(lesson_id, audio_path):
                raise error
            return fake

        # 7а. Ошибка SQLite -> понятная StorageError, копия удалена.
        storage.set_lesson_audio_path = failing(sqlite3.OperationalError("database is locked"))
        try:
            error = raised(storage.StorageError, lesson_audio.attach_audio_to_lesson, lesson.id, db_source)
        finally:
            storage.set_lesson_audio_path = real_set_path
        check(is_russian(error), "ошибка SQLite превращается в StorageError с сообщением на русском")
        check(error is not None and "удалена" in str(error), "в сообщении сказано, что копия удалена")
        check(file_names(audio_dir) == names_before, "лишняя копия удалена, другие файлы на месте")
        check(storage.get_lesson(lesson.id) == lesson_now, "запись урока не изменилась")
        check(db_source.is_file() and sha256(db_source) == db_source_hash, "оригинал цел")

        # 7б. Неожиданная ошибка -> не скрывается, копия всё равно удаляется.
        storage.set_lesson_audio_path = failing(RuntimeError("неожиданный сбой"))
        try:
            error = raised(RuntimeError, lesson_audio.attach_audio_to_lesson, lesson.id, db_source)
        finally:
            storage.set_lesson_audio_path = real_set_path
        check(error is not None, "неожиданная ошибка не скрывается")
        check(file_names(audio_dir) == names_before, "после неожиданной ошибки копия тоже удалена")

        # 7в. Урок исчез между проверкой и записью -> NotFoundError, копия удалена.
        storage.set_lesson_audio_path = failing(storage.NotFoundError("Урок с номером 1 не найден."))
        try:
            error = raised(storage.NotFoundError, lesson_audio.attach_audio_to_lesson, lesson.id, db_source)
        finally:
            storage.set_lesson_audio_path = real_set_path
        check(error is not None, "если урок исчез, выдаётся NotFoundError")
        check(file_names(audio_dir) == names_before, "в этом случае копия тоже удалена")

        # 7г. Копию удалить нельзя -> ошибка честно об этом сообщает.
        real_unlink = pathlib.Path.unlink

        def locked_unlink(self, missing_ok=False):
            raise PermissionError("файл занят")

        storage.set_lesson_audio_path = failing(sqlite3.OperationalError("disk I/O error"))
        pathlib.Path.unlink = locked_unlink
        try:
            error = raised(storage.StorageError, lesson_audio.attach_audio_to_lesson, lesson.id, db_source)
        finally:
            pathlib.Path.unlink = real_unlink
            storage.set_lesson_audio_path = real_set_path
        leftovers = sorted(set(file_names(audio_dir)) - set(names_before))
        check(
            error is not None and "осталась" in str(error),
            "если копию удалить не удалось, сообщение об этом говорит",
        )
        check(len(leftovers) == 1, "оставшаяся копия видна и названа в сообщении")
        check(
            error is not None and len(leftovers) == 1 and leftovers[0] in str(error),
            "в сообщении указано имя оставшейся копии",
        )
        for name in leftovers:
            (audio_dir / name).unlink()  # убираем за тестом
        check(file_names(audio_dir) == names_before, "после уборки папка audio в прежнем состоянии")
        check(db_source.is_file(), "оригинал после всех сбоев цел")

        # 7д. После сбоев всё работает как раньше.
        after_failures = lesson_audio.attach_audio_to_lesson(lesson.id, db_source)
        check(
            Path(after_failures.audio_path).is_file()
            and sha256(Path(after_failures.audio_path)) == db_source_hash,
            "после сбоев привязка снова работает",
        )
        first_copy = saved
        second_copy = Path(after_failures.audio_path)

        print("8. Повторная привязка")
        check(second_copy != first_copy, "второй файл получил свою копию")
        check(
            storage.get_lesson(lesson.id).audio_path == str(second_copy),
            "в уроке теперь путь к новой копии",
        )
        check(
            first_copy.is_file() and sha256(first_copy) == source_hash,
            "прежняя копия не удалена и не изменена (так задумано)",
        )
        again = lesson_audio.attach_audio_to_lesson(lesson.id, second_copy)
        third_copy = Path(again.audio_path)
        check(
            third_copy != second_copy and third_copy.is_file() and second_copy.is_file(),
            "файл из папки audio как источник: делается новая копия, источник не удалён",
        )
        check(sha256(third_copy) == db_source_hash, "содержимое этой копии верное")

        print("9. Нет интернета, распознавания и новых зависимостей")
        tree = ast.parse(Path(lesson_audio.__file__).read_text(encoding="utf-8"))
        absolute_imports = set()
        relative_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                absolute_imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    absolute_imports.add(node.module.split(".")[0])
                else:
                    relative_imports.update(alias.name for alias in node.names)
        check(
            absolute_imports <= {"__future__", "os", "sqlite3", "pathlib"},
            f"lesson_audio.py импортирует только встроенные модули {sorted(absolute_imports)}",
        )
        check(
            relative_imports == {"audio", "storage"},
            f"из проекта используются только audio и storage {sorted(relative_imports)}",
        )
        check(
            not any(
                m in sys.modules
                for m in ("konspekt.transcription", "konspekt.transcribe", "openai", "requests")
            ),
            "модули распознавания и сетевые библиотеки не загружались",
        )

        print("10. Итог по данным")
        check(
            [storage.get_lesson(neighbour_same.id), storage.get_lesson(neighbour_other.id)]
            == neighbours_before,
            "соседние уроки не менялись за всё время проверки",
        )
        check(
            storage.get_lesson(lesson.id).title == "Законы Ньютона"
            and storage.get_lesson(lesson.id).transcript == "Распознанный текст урока",
            "название и текст проверяемого урока на месте",
        )

    print("11. Настоящие данные проекта")
    check(
        snapshot_tree(PROJECT_ROOT / "data") == real_data_before,
        "папка data/ проекта не создана и не изменена",
    )

    print()
    if failures:
        print(f"ИТОГ: проверок не пройдено: {failures}")
        sys.exit(1)
    print("ИТОГ: все проверки пройдены.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Непредвиденная ошибка внутри проверки: показываем её и считаем проверку проваленной.
        traceback.print_exc()
        print()
        print("ИТОГ: проверка прервана из-за непредвиденной ошибки (см. выше).")
        sys.exit(1)
