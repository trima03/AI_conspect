"""Создаёт ДЕМОНСТРАЦИОННЫЕ данные, чтобы посмотреть интерфейс с лекциями.

Запуск из корня проекта:  python make_demo_data.py

Данные создаются во ВРЕМЕННОЙ папке Windows (папка Temp, подпапка konspekt_demo),
а не в папке data вашего проекта. Настоящая база не затрагивается. «Аудиофайлы» здесь
просто случайные байты с расширением .mp3: они нужны только для показа
интерфейса и не воспроизводятся. Если демо-данные уже есть, скрипт ничего не
меняет и просто напоминает команду запуска.
"""

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Чтобы не нужно было устанавливать проект, подключаем папку src вручную.
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from konspekt import lesson_audio, storage  # noqa: E402

DEMO_DIR = Path(tempfile.gettempdir()) / "konspekt_demo"

# (предмет, название лекции, статус, текст ошибки)
DEMO_LESSONS = [
    ("Физика", "Законы Ньютона", storage.STATUS_COMPLETED, None),
    ("Физика", "Закон сохранения энергии", storage.STATUS_PROCESSING, None),
    ("Математика", "Производные функций", storage.STATUS_QUEUED, None),
    (
        "Математика",
        "Интегралы",
        storage.STATUS_FAILED,
        "Не удалось подключиться к сервису распознавания. "
        "Проверьте интернет и попробуйте ещё раз.",
    ),
    ("История", "Реформы Петра I", storage.STATUS_QUEUED, None),
    ("История", "Отечественная война 1812 года", storage.STATUS_COMPLETED, None),
]


def main() -> None:
    os.environ[storage.DATA_DIR_ENV_VAR] = str(DEMO_DIR)
    storage.init_db()

    if storage.list_subjects():
        print("Демо-данные уже созданы, ничего не меняю.")
    else:
        subjects = {}
        with tempfile.TemporaryDirectory(prefix="konspekt_demo_src_") as source_dir:
            for number, (subject_name, title, status, error) in enumerate(DEMO_LESSONS, 1):
                if subject_name not in subjects:
                    subjects[subject_name] = storage.create_subject(subject_name)
                fake_audio = Path(source_dir) / f"demo_{number}.mp3"
                fake_audio.write_bytes(os.urandom(2048))
                lesson = lesson_audio.create_lesson_with_audio(
                    subjects[subject_name].id, title, fake_audio
                )
                if status != storage.STATUS_QUEUED:
                    storage.set_lesson_status(lesson.id, status, error)
        print(f"Создано: предметов {len(subjects)}, лекций {len(DEMO_LESSONS)}.")

    print(f"Папка демо-данных: {DEMO_DIR}")
    print()
    print("Запуск приложения с демо-данными:")
    print(f'    python run_app.py --data-dir "{DEMO_DIR}"')


if __name__ == "__main__":
    main()
