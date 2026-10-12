"""Проверка создания урока с аудио одной операцией (create_lesson_with_audio).

Запуск из корня проекта:  python check_create_lesson.py
Используются временная папка и временная база SQLite. Настоящая папка data/
проекта не меняется. Тестовые файлы создаются сами и удаляются в конце.
"""

import ast
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


def all_lessons() -> list:
    """Все уроки всех предметов, по возрастанию номера."""
    lessons = []
    for subject in storage.list_subjects():
        lessons.extend(storage.list_lessons(subject.id))
    return sorted(lessons, key=lambda lesson: lesson.id)


def world() -> tuple:
    """Всё состояние данных: предметы, уроки и файлы в папке audio."""
    return (
        storage.list_subjects(),
        all_lessons(),
        snapshot_tree(storage.get_audio_dir()),
    )


def run_sql(sql: str) -> None:
    """Выполняет SQL напрямую в базе (нужно, чтобы вызвать настоящий сбой SQLite)."""
    conn = sqlite3.connect(storage.get_db_path())
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    real_data_before = snapshot_tree(PROJECT_ROOT / "data")

    with tempfile.TemporaryDirectory(prefix="konspekt_create_lesson_check_") as temp_dir:
        temp_path = Path(temp_dir).resolve()
        data_dir = temp_path / "data"
        source_dir = temp_path / "source"
        source_dir.mkdir()

        # Направляем storage.py (а значит, audio.py и lesson_audio.py) во временную папку.
        os.environ[storage.DATA_DIR_ENV_VAR] = str(data_dir)
        storage.init_db()
        audio_dir = storage.get_audio_dir()

        # Исходные файлы, которые не должны меняться ни при каких сценариях.
        sources = {}

        def new_source(name: str, content: bytes) -> Path:
            path = source_dir / name
            path.write_bytes(content)
            sources[path] = sha256(path)
            return path

        print("1. Безопасность проверки")
        check(temp_path in storage.get_db_path().parents, "база для проверки лежит во временной папке")
        check(temp_path in audio_dir.parents, "папка для копий лежит во временной папке")
        check(
            storage.get_db_path() != PROJECT_ROOT / "data" / "konspekt.db",
            "это не настоящая база проекта",
        )

        # --- Уже существующие данные, которые должны остаться нетронутыми ---
        physics = storage.create_subject("Физика")
        math_subject = storage.create_subject("Математика")
        empty_subject = storage.create_subject("Пустой предмет")

        old_source = new_source("old_lesson.mp3", os.urandom(2048))
        old_copy = audio.save_audio(old_source)
        old_lesson = storage.create_lesson(physics.id, "Старая лекция", old_copy)
        storage.set_lesson_status(old_lesson.id, storage.STATUS_FAILED, "Нет сети")
        old_placeholder = storage.create_lesson(math_subject.id, "Другая старая", "pending/placeholder.mp3")
        old_lesson = storage.get_lesson(old_lesson.id)
        old_copy_hash = sha256(old_copy)
        old_copy_info = old_copy.stat()
        world_before = world()

        created = []  # уроки, созданные проверяемой функцией

        print("2. Успешное создание урока с аудио")
        content = os.urandom(3 * 1024 * 1024 + 5)  # больше одного куска копирования
        source = new_source("lesson_newton.mp3", content)
        source_info = source.stat()
        files_before = file_names(audio_dir)
        lessons_before = all_lessons()

        result = lesson_audio.create_lesson_with_audio(physics.id, "  Законы Ньютона  ", source)
        created.append(result)
        stored = storage.get_lesson(result.id)
        saved = Path(result.audio_path)
        new_files = sorted(set(file_names(audio_dir)) - set(files_before))
        new_lessons = [x for x in all_lessons() if x not in lessons_before]

        check(isinstance(result, storage.Lesson), "функция возвращает созданный урок")
        check(result == stored, "возвращённый урок совпадает с записью в базе")
        check(result.status == storage.STATUS_QUEUED, "статус нового урока: queued")
        check(result.title == "Законы Ньютона", "пробелы в названии убраны")
        check(result.subject_id == physics.id, "урок относится к нужному предмету")
        check(
            result.transcript is None and result.summary is None and result.error_message is None,
            "текст, конспект и ошибка пока пустые",
        )
        check(saved.is_file(), "путь в записи указывает на существующий файл")
        check(saved.parent == audio_dir, "копия лежит в папке data/audio")
        check(saved.suffix == ".mp3", "у копии то же расширение")
        check(len(new_files) == 1 and new_files[0] == saved.name, "в папке audio появилась ровно одна копия")
        check(len(new_lessons) == 1 and new_lessons[0] == result, "в базе появилась ровно одна новая запись")
        check(source.is_file() and sha256(saved) == sha256(source), "содержимое копии совпадает с оригиналом байт в байт")
        check(saved.stat().st_size == len(content), "размер копии совпадает с оригиналом")
        check(source.is_file(), "оригинал остался на месте")
        check(
            source.is_file()
            and source.stat().st_size == source_info.st_size
            and source.stat().st_mtime_ns == source_info.st_mtime_ns,
            "размер и время изменения оригинала не изменились",
        )
        check(file_names(source_dir) == sorted(p.name for p in sources), "в папке с оригиналами ничего не добавилось и не пропало")

        print("3. Разные способы передать файл и разные форматы")
        m4a = new_source("Лекция по интегралам.m4a", os.urandom(1500))
        wav = new_source("RECORD.WAV", os.urandom(1200))
        flac = new_source("sound.flac", os.urandom(900))
        by_str = lesson_audio.create_lesson_with_audio(math_subject.id, "Интегралы", str(m4a))
        by_path = lesson_audio.create_lesson_with_audio(math_subject.id, "Пределы", wav)
        in_empty = lesson_audio.create_lesson_with_audio(empty_subject.id, "Первая лекция", flac)
        created.extend([by_str, by_path, in_empty])
        check(
            Path(by_str.audio_path).suffix == ".m4a" and Path(by_str.audio_path).read_bytes() == m4a.read_bytes(),
            "путь в виде строки и русское имя файла: копия верная",
        )
        check(
            Path(by_path.audio_path).suffix == ".wav" and Path(by_path.audio_path).read_bytes() == wav.read_bytes(),
            "путь в виде Path и расширение .WAV: копия верная",
        )
        check(
            [x.title for x in storage.list_lessons(empty_subject.id)] == ["Первая лекция"],
            "лекцию можно создать в предмете, где ещё не было лекций",
        )
        check(
            [x.title for x in storage.list_lessons(physics.id)] == ["Старая лекция", "Законы Ньютона"]
            and [x.title for x in storage.list_lessons(math_subject.id)]
            == ["Другая старая", "Интегралы", "Пределы"],
            "лекции лежат в своих предметах, в порядке создания",
        )

        print("4. Один файл — две лекции")
        first = lesson_audio.create_lesson_with_audio(physics.id, "Повтор 1", source)
        second = lesson_audio.create_lesson_with_audio(physics.id, "Повтор 2", source)
        created.extend([first, second])
        check(first.audio_path != second.audio_path, "каждая лекция получила свою копию")
        check(
            Path(first.audio_path).is_file() and Path(second.audio_path).is_file(),
            "обе копии существуют",
        )
        check(
            source.is_file()
            and sha256(Path(first.audio_path)) == sha256(source) == sha256(Path(second.audio_path)),
            "обе копии совпадают с оригиналом",
        )

        print("5. Ошибки до копирования: ничего не создаётся и не меняется")

        def expect_clean_failure(label: str, error_type: type, *args) -> None:
            before = world()
            error = raised(error_type, lesson_audio.create_lesson_with_audio, *args)
            check(is_russian(error), f"{label}: {error_type.__name__}, сообщение на русском")
            check(world() == before, f"{label}: ни лекций, ни файлов не добавилось, остальное не изменилось")

        for bad_subject in (9999, 0, -1, None):
            expect_clean_failure(f"предмета {bad_subject!r} нет", storage.NotFoundError, bad_subject, "Название", source)
        for bad_title in ("", "   ", "\t\n", None, 123):
            expect_clean_failure(f"название {bad_title!r}", ValueError, physics.id, bad_title, source)

        wrong_format = new_source("notes.txt", b"not audio")
        empty_file = new_source("empty.mp3", b"")
        too_big = source_dir / "too_big.wav"
        with open(too_big, "wb") as big_file:
            big_file.truncate(audio.MAX_SIZE_BYTES + 1)
        expect_clean_failure("формат .txt", audio.UnsupportedAudioFormatError, physics.id, "Название", wrong_format)
        expect_clean_failure("размер больше 25 МБ", audio.AudioTooLargeError, physics.id, "Название", too_big)
        expect_clean_failure("файла нет", audio.AudioFileNotFoundError, physics.id, "Название", source_dir / "missing.mp3")
        expect_clean_failure("пустой файл", audio.AudioError, physics.id, "Название", empty_file)
        expect_clean_failure("вместо файла папка", audio.AudioError, physics.id, "Название", source_dir)
        expect_clean_failure("путь не указан", audio.AudioError, physics.id, "Название", "")

        print("   Порядок проверок: предмет, потом название, потом аудио")
        expect_clean_failure("нет предмета и плохое название", storage.NotFoundError, 9999, "", wrong_format)
        expect_clean_failure("плохое название и плохой файл", ValueError, physics.id, "", wrong_format)
        check(too_big.is_file() and wrong_format.is_file(), "отклонённые исходные файлы на месте")

        print("6. Настоящий сбой SQLite после копирования (через триггер в базе)")
        # Триггер заставляет базу отвергнуть вставку лекции. Код проекта при этом
        # не подменяется: ошибку выдаёт сама SQLite, после того как копия уже создана.
        before = world()
        run_sql(
            "CREATE TRIGGER block_insert BEFORE INSERT ON lessons "
            "BEGIN SELECT RAISE(ABORT, 'тестовый запрет вставки'); END;"
        )
        try:
            error = raised(storage.StorageError, lesson_audio.create_lesson_with_audio, physics.id, "Не получится", source)
        finally:
            run_sql("DROP TRIGGER block_insert;")
        check(is_russian(error), "ошибка SQLite превращается в StorageError на русском")
        check(error is not None and "удалена" in str(error), "в сообщении сказано, что копия удалена")
        check(world() == before, "лекция не появилась, копия удалена, остальное не изменилось")

        # Здесь вставка сначала проходит, а сбой случается уже после неё.
        run_sql(
            "CREATE TRIGGER fail_after AFTER INSERT ON lessons "
            "BEGIN SELECT RAISE(ABORT, 'сбой после вставки'); END;"
        )
        try:
            error = raised(storage.StorageError, lesson_audio.create_lesson_with_audio, physics.id, "Не получится", source)
        finally:
            run_sql("DROP TRIGGER fail_after;")
        check(error is not None, "сбой уже после вставки тоже даёт понятную ошибку")
        check(world() == before, "вставка откатилась целиком: нет ни записи, ни копии")

        print("7. Другие сбои после копирования (подмена функции создания записи)")
        real_create_lesson = storage.create_lesson

        def failing(error):
            def fake(*args, **kwargs):
                raise error
            return fake

        before = world()
        source_hash = sources[source]

        storage.create_lesson = failing(sqlite3.OperationalError("database is locked"))
        try:
            error = raised(storage.StorageError, lesson_audio.create_lesson_with_audio, physics.id, "Сбой", source)
        finally:
            storage.create_lesson = real_create_lesson
        check(is_russian(error) and "удалена" in str(error), "блокировка базы: StorageError, копия удалена")
        check(world() == before, "после блокировки базы данные не изменились")

        storage.create_lesson = failing(RuntimeError("неожиданный сбой"))
        try:
            error = raised(RuntimeError, lesson_audio.create_lesson_with_audio, physics.id, "Сбой", source)
        finally:
            storage.create_lesson = real_create_lesson
        check(error is not None, "неожиданная ошибка не скрывается")
        check(world() == before, "после неожиданной ошибки копия тоже удалена")

        storage.create_lesson = failing(ValueError("Название урока не может быть пустым."))
        try:
            error = raised(ValueError, lesson_audio.create_lesson_with_audio, physics.id, "Сбой", source)
        finally:
            storage.create_lesson = real_create_lesson
        check(error is not None and world() == before, "ошибка проверки внутри storage: копия удалена")

        storage.create_lesson = failing(storage.NotFoundError("Предмет с номером 1 не найден."))
        try:
            error = raised(storage.NotFoundError, lesson_audio.create_lesson_with_audio, physics.id, "Сбой", source)
        finally:
            storage.create_lesson = real_create_lesson
        check(error is not None and world() == before, "предмет исчез между проверкой и записью: копия удалена")

        interrupted = False
        storage.create_lesson = failing(KeyboardInterrupt())
        try:
            try:
                lesson_audio.create_lesson_with_audio(physics.id, "Сбой", source)
            except KeyboardInterrupt:
                interrupted = True
        finally:
            storage.create_lesson = real_create_lesson
        check(interrupted, "прерывание (Ctrl+C) не скрывается")
        check(world() == before, "после прерывания копия тоже удалена")

        # Копию удалить нельзя: ошибка должна честно об этом сообщить.
        real_unlink = pathlib.Path.unlink

        def locked_unlink(self, missing_ok=False):
            raise PermissionError("файл занят")

        storage.create_lesson = failing(sqlite3.OperationalError("disk I/O error"))
        pathlib.Path.unlink = locked_unlink
        try:
            error = raised(storage.StorageError, lesson_audio.create_lesson_with_audio, physics.id, "Сбой", source)
        finally:
            pathlib.Path.unlink = real_unlink
            storage.create_lesson = real_create_lesson
        leftovers = sorted(set(file_names(audio_dir)) - set(before[2].keys()))
        check(error is not None and "осталась" in str(error), "если копию удалить не удалось, сообщение об этом говорит")
        check(
            error is not None and len(leftovers) == 1 and leftovers[0] in str(error),
            "в сообщении указано имя оставшейся копии",
        )
        check(all_lessons() == before[1], "даже в этом случае записи об уроке в базе нет")
        for name in leftovers:
            (audio_dir / name).unlink()  # убираем за тестом
        check(world() == before, "после уборки данные в прежнем состоянии")
        check(source.is_file() and sha256(source) == source_hash, "оригинал после всех сбоев цел")

        again = lesson_audio.create_lesson_with_audio(physics.id, "После сбоев", source)
        created.append(again)
        check(
            Path(again.audio_path).is_file() and sha256(Path(again.audio_path)) == source_hash,
            "после сбоев создание лекций снова работает",
        )

        print("8. Нет лекций без аудио и нет лишних файлов")
        check(
            all(Path(x.audio_path).is_file() for x in created),
            "у каждой созданной лекции есть файл аудио",
        )
        check(
            all(storage.get_lesson(x.id) == x and x.status == storage.STATUS_QUEUED for x in created),
            "все созданные лекции записаны в базу со статусом queued",
        )
        expected_files = sorted([old_copy.name] + [Path(x.audio_path).name for x in created])
        check(
            file_names(audio_dir) == expected_files,
            "в папке audio лежат только старая копия и копии созданных лекций, ничего лишнего",
        )

        print("9. Существующие данные не повреждены")
        check(storage.get_lesson(old_lesson.id) == old_lesson, "старая лекция с ошибкой и статусом failed не изменилась")
        check(storage.get_lesson(old_placeholder.id) == old_placeholder, "вторая старая лекция не изменилась")
        check(
            old_copy.is_file() and sha256(old_copy) == old_copy_hash
            and old_copy.stat().st_mtime_ns == old_copy_info.st_mtime_ns,
            "старый аудиофайл на месте и не изменился",
        )
        check(
            [x for x in storage.list_subjects()] == world_before[0],
            "предметы не изменились",
        )
        check(
            [x for x in all_lessons() if x not in created] == world_before[1],
            "кроме новых, в базе те же лекции, что и были",
        )
        check(
            all(path.is_file() and sha256(path) == digest for path, digest in sources.items()),
            "все исходные файлы на месте и не изменились за всё время проверки",
        )
        check(
            source.is_file() and source.stat().st_mtime_ns == source_info.st_mtime_ns,
            "время изменения главного исходного файла не изменилось",
        )

        print("10. Старая функция attach_audio_to_lesson по-прежнему работает")
        extra = new_source("replacement.ogg", os.urandom(1000))
        target = created[0]
        attached = lesson_audio.attach_audio_to_lesson(target.id, extra)
        check(
            Path(attached.audio_path).is_file()
            and Path(attached.audio_path).read_bytes() == extra.read_bytes()
            and attached.audio_path != target.audio_path,
            "аудио привязывается к лекции, созданной новой функцией",
        )

        print("11. Нет интернета, распознавания и новых зависимостей")
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

    print("12. Настоящие данные проекта")
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
