"""Проверка audio.py на ВРЕМЕННЫХ папках и тестовых файлах.

Запуск из корня проекта:  python check_audio.py
Настоящие аудиозаписи не используются, настоящая папка data/ не меняется.
"""

import ast
import errno
import hashlib
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Чтобы не нужно было устанавливать проект, подключаем папку src вручную.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from konspekt import audio, storage  # noqa: E402

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


def snapshot_tree(path: Path):
    """Запоминает состояние папки (имена, размеры, время изменения)."""
    if not path.exists():
        return None
    result = {}
    for item in sorted(path.rglob("*")):
        info = item.stat()
        result[str(item.relative_to(path))] = (info.st_size, info.st_mtime_ns)
    return result


def file_names(folder: Path) -> list:
    return sorted(item.name for item in folder.iterdir())


def main() -> None:
    real_data_before = snapshot_tree(PROJECT_ROOT / "data")

    with tempfile.TemporaryDirectory(prefix="konspekt_audio_check_") as temp_dir:
        temp_path = Path(temp_dir).resolve()
        data_dir = temp_path / "data"
        source_dir = temp_path / "source"
        source_dir.mkdir()

        # Направляем storage.py (а значит, и audio.py) во временную папку.
        os.environ[storage.DATA_DIR_ENV_VAR] = str(data_dir)
        audio_dir = storage.get_audio_dir()

        print("1. Безопасность проверки")
        check(
            temp_path in audio_dir.parents,
            "папка для копий лежит во временной папке",
        )
        check(
            audio_dir != PROJECT_ROOT / "data" / "audio",
            "это не настоящая папка data/audio проекта",
        )

        print("2. Настройки модуля")
        check(
            audio.ALLOWED_EXTENSIONS
            == {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"},
            "список форматов: flac, mp3, mp4, mpeg, mpga, m4a, ogg, wav, webm",
        )
        check(audio.MAX_SIZE_BYTES == 25 * 1024 * 1024, "лимит размера: 25 МБ")

        print("3. Допустимые форматы")
        for extension in sorted(audio.ALLOWED_EXTENSIONS):
            content = os.urandom(2048)
            source = make_file(source_dir, f"lesson{extension}", content)
            saved = audio.save_audio(source)
            check(
                saved.is_file()
                and saved.suffix == extension
                and saved.read_bytes() == content,
                f"{extension}: файл скопирован, расширение и содержимое сохранены",
            )
            check(saved.parent == audio_dir, f"{extension}: копия лежит в папке audio")
        upper = make_file(source_dir, "Lecture.MP3", os.urandom(512))
        saved_upper = audio.save_audio(upper)
        check(saved_upper.suffix == ".mp3", "расширение .MP3 принимается и в копии становится .mp3")
        check(
            audio.save_audio(str(make_file(source_dir, "text.wav", b"RIFF1234"))).is_file(),
            "путь можно передать обычной строкой",
        )

        print("4. Недопустимые форматы")
        files_before = file_names(audio_dir)
        bad_files = [
            "notes.txt",
            "document.pdf",
            "program.exe",
            "archive.zip",
            "double.mp3.txt",
            "no_extension",
            ".mp3",  # имя без названия: в Windows это файл без расширения
        ]
        for name in bad_files:
            bad = make_file(source_dir, name, b"some bytes")
            error = raised(audio.UnsupportedAudioFormatError, audio.save_audio, bad)
            check(
                error is not None and is_russian(error),
                f"«{name}» отклонён с сообщением на русском",
            )
        check(
            "mp3" in str(raised(audio.UnsupportedAudioFormatError, audio.save_audio,
                                source_dir / "notes.txt")),
            "в сообщении перечислены допустимые форматы",
        )
        check(file_names(audio_dir) == files_before, "отклонённые файлы не попали в папку audio")

        print("5. Файл не существует и неверный путь")
        error = raised(audio.AudioFileNotFoundError, audio.save_audio, source_dir / "missing.mp3")
        check(is_russian(error), "несуществующий файл: AudioFileNotFoundError, сообщение на русском")
        error = raised(audio.AudioError, audio.save_audio, source_dir)
        check(is_russian(error), "вместо файла указана папка: сообщение на русском")
        error = raised(audio.AudioError, audio.save_audio, "")
        check(is_russian(error), "пустая строка вместо пути: сообщение на русском")
        error = raised(audio.AudioError, audio.save_audio, None)
        check(is_russian(error), "None вместо пути: сообщение на русском")
        error = raised(audio.AudioError, audio.save_audio, 12345)
        check(is_russian(error), "число вместо пути: сообщение на русском")
        check(file_names(audio_dir) == files_before, "после этих ошибок в папке audio ничего не появилось")

        print("6. Ограничение размера")
        limit = audio.MAX_SIZE_BYTES
        exact = make_sized_file(source_dir, "exact_limit.mp3", limit)
        check(audio.validate_audio_file(exact) == exact, "файл ровно 25 МБ допускается")
        over = make_sized_file(source_dir, "over_limit.mp3", limit + 1)
        error = raised(audio.AudioTooLargeError, audio.save_audio, over)
        check(is_russian(error), "файл на 1 байт больше лимита отклоняется")
        check(error is not None and "25" in str(error), "в сообщении указан лимит 25 МБ")
        huge = make_sized_file(source_dir, "huge.wav", limit * 2)
        check(
            raised(audio.AudioTooLargeError, audio.save_audio, huge) is not None,
            "файл 50 МБ отклоняется",
        )
        empty = make_file(source_dir, "empty.mp3", b"")
        error = raised(audio.AudioError, audio.save_audio, empty)
        check(is_russian(error), "пустой файл (0 байт) отклоняется")
        names_now = file_names(audio_dir)
        check(
            not any("over_limit" in n or "huge" in n or "empty" in n for n in names_now),
            "слишком большие и пустые файлы не скопированы",
        )

        print("7. Содержимое копии и неизменность оригинала")
        content = os.urandom(3 * 1024 * 1024 + 17)  # больше одного куска копирования
        original = make_file(source_dir, "big_lesson.flac", content)
        info_before = original.stat()
        hash_before = sha256(original)
        saved = audio.save_audio(original)
        check(sha256(saved) == hash_before, "копия совпадает с оригиналом байт в байт (3 МБ)")
        check(saved.stat().st_size == len(content), "размер копии совпадает с оригиналом")
        info_after = original.stat()
        check(original.is_file(), "оригинал на месте (не удалён и не перемещён)")
        check(sha256(original) == hash_before, "содержимое оригинала не изменилось")
        check(
            info_after.st_size == info_before.st_size
            and info_after.st_mtime_ns == info_before.st_mtime_ns,
            "размер и время изменения оригинала не изменились",
        )
        check(saved != original, "копия и оригинал — разные файлы")

        print("8. Уникальные имена")
        one_source = make_file(source_dir, "same.mp3", os.urandom(1024))
        saved_paths = [audio.save_audio(one_source) for _ in range(30)]
        check(len({p.name for p in saved_paths}) == 30, "30 копий одного файла получили 30 разных имён")
        check(all(p.is_file() for p in saved_paths), "все 30 копий существуют")
        check(
            all(sha256(p) == sha256(one_source) for p in saved_paths),
            "все 30 копий содержат те же данные",
        )

        folder_a = source_dir / "a"
        folder_b = source_dir / "b"
        folder_a.mkdir()
        folder_b.mkdir()
        content_a, content_b = b"AAAA" * 100, b"BBBB" * 100
        saved_a = audio.save_audio(make_file(folder_a, "урок.mp3", content_a))
        saved_b = audio.save_audio(make_file(folder_b, "урок.mp3", content_b))
        check(saved_a != saved_b, "одинаковые имена из разных папок не конфликтуют")
        check(
            saved_a.read_bytes() == content_a and saved_b.read_bytes() == content_b,
            "каждая копия хранит своё содержимое (ничего не перезаписано)",
        )

        print("9. Безопасность имён")
        tricky = make_file(source_dir, "Урок №1 (физика) — 09.10.mp3", os.urandom(256))
        saved = audio.save_audio(tricky)
        check(saved.parent == audio_dir, "русское имя с пробелами и символами: копия в папке audio")
        check(
            re.fullmatch(r"[\w\-]+\.mp3", saved.name) is not None,
            "в имени копии нет пробелов и спецсимволов",
        )
        check(saved.name.startswith("Урок"), "имя копии хранит читаемую часть исходного названия")
        dotted = make_file(source_dir, "..evil.mp3", os.urandom(256))
        saved = audio.save_audio(dotted)
        check(
            saved.parent == audio_dir and not saved.name.startswith("."),
            "имя, начинающееся с точек, безопасно",
        )

        dangerous_stems = [
            "../../evil",
            "..\\..\\evil",
            "C:\\Windows\\system32\\config",
            "/etc/passwd",
            "a/b",
            "con",
            "nul",
            "",
            "   ",
            "...",
            "-rf",
            "name\x00null",
            "x" * 500,
        ]
        bad_chars = set('/\\:*?"<>|\x00')
        safe_names = True
        for stem in dangerous_stems:
            name = audio._make_unique_name(stem, ".mp3")
            resolved_parent = (audio_dir / name).resolve().parent
            ok = (
                not (bad_chars & set(name))
                and name.endswith(".mp3")
                and not name.startswith((".", "-", "_"))
                and len(name) <= 80
                and resolved_parent == audio_dir.resolve()
            )
            if not ok:
                safe_names = False
                print(f"        (небезопасное имя для {stem!r}: {name!r})")
        check(safe_names, "опасные названия ('../', '..\\', 'C:\\', 'con', очень длинные) делают безопасное имя")
        generated = {audio._make_unique_name("lesson", ".mp3") for _ in range(1000)}
        check(len(generated) == 1000, "1000 сгенерированных имён подряд не повторились")

        print("10. Сбои при копировании")
        source = make_file(source_dir, "will_fail.mp3", os.urandom(5000))
        names_before = file_names(audio_dir)
        real_copy = audio.shutil.copyfileobj

        def disk_full(src, dst, length=0):
            dst.write(src.read(10))
            raise OSError(errno.ENOSPC, "No space left on device")

        audio.shutil.copyfileobj = disk_full
        try:
            error = raised(audio.AudioError, audio.save_audio, source)
        finally:
            audio.shutil.copyfileobj = real_copy
        check(error is not None and "места" in str(error), "нет места на диске: понятное сообщение на русском")
        check(file_names(audio_dir) == names_before, "недокопированный файл удалён")

        def short_copy(src, dst, length=0):
            dst.write(src.read(100))  # копируем только начало

        audio.shutil.copyfileobj = short_copy
        try:
            error = raised(audio.AudioError, audio.save_audio, source)
        finally:
            audio.shutil.copyfileobj = real_copy
        check(is_russian(error), "неполная копия обнаруживается, сообщение на русском")
        check(file_names(audio_dir) == names_before, "неполная копия удалена")
        check(source.is_file() and source.stat().st_size == 5000, "оригинал после сбоев цел")
        check(audio.save_audio(source).is_file(), "после сбоев копирование снова работает")

        print("11. Нет интернета, распознавания и базы данных")
        tree = ast.parse(Path(audio.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        allowed_imports = {"__future__", "errno", "os", "re", "shutil", "uuid", "pathlib"}
        check(
            imported <= allowed_imports,
            f"audio.py импортирует только встроенные модули для файлов {sorted(imported)}",
        )
        check(
            not any(
                m in sys.modules
                for m in ("konspekt.transcription", "konspekt.transcribe", "openai", "requests")
            ),
            "модули распознавания и сетевые библиотеки не загружались",
        )
        check(
            not (data_dir / "konspekt.db").exists(),
            "база данных не создавалась и не менялась",
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
