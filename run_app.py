"""Запуск AIKonspekt из корня проекта:  python run_app.py

Необязательный параметр:
    --data-dir ПАПКА   хранить данные не в data/ проекта, а в указанной папке
                       (удобно для проб: настоящая база остаётся нетронутой).
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Чтобы не нужно было устанавливать проект, подключаем папку src вручную.
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIKonspekt: конспекты лекций")
    parser.add_argument(
        "--data-dir",
        help="папка для данных (по умолчанию: папка data в проекте)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    from konspekt import storage

    if args.data_dir:
        os.environ[storage.DATA_DIR_ENV_VAR] = args.data_dir

    from konspekt.ui.main import main

    sys.exit(main())
