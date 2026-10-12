"""Запуск приложения AIKonspekt.

Запускать нужно через run_app.py в корне проекта (python run_app.py).
Этот файл напрямую не запускается: он часть пакета konspekt.ui.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import storage
from .main_window import MainWindow
from .styles import build_stylesheet

logger = logging.getLogger("konspekt")

_handling_error = False  # защита от повторного показа окна ошибки


def _setup_logging() -> None:
    """Журнал: в консоль и в файл data/logs/aikonspekt.log."""
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    log_dir = storage.get_data_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "aikonspekt.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("Не удалось создать файл журнала в папке %s", log_dir)


def _install_exception_hook() -> None:
    """Непредвиденные ошибки: подробности в журнал, пользователю короткое сообщение."""

    def hook(exc_type, exc_value, exc_traceback) -> None:
        global _handling_error
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "Необработанная ошибка", exc_info=(exc_type, exc_value, exc_traceback)
        )
        if _handling_error or QApplication.instance() is None:
            return
        _handling_error = True
        try:
            QMessageBox.critical(
                None,
                "AIKonspekt",
                "Произошла непредвиденная ошибка.\n\n"
                "Подробности записаны в журнал (папка data/logs). "
                "Лучше перезапустить приложение.",
            )
        finally:
            _handling_error = False

    sys.excepthook = hook


def _force_light_scheme(app: QApplication) -> None:
    """Светлая тема независимо от настроек Windows (нужна Qt 6.8 или новее)."""
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except AttributeError:
        logger.warning("Эта версия Qt не умеет принудительно включать светлую тему")


def main(argv: list[str] | None = None) -> int:
    """Создаёт приложение, готовит базу и показывает главное окно."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AIKonspekt")
    app.setStyle("Fusion")  # единая основа для наших стилей
    _force_light_scheme(app)
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(build_stylesheet())

    _setup_logging()
    _install_exception_hook()
    logger.info("Папка данных: %s", storage.get_data_dir())

    try:
        storage.init_db()
    except Exception:
        logger.exception("Не удалось подготовить базу данных")
        QMessageBox.critical(
            None,
            "AIKonspekt",
            "Не удалось подготовить базу данных.\n\n"
            "Подробности записаны в журнал (папка data/logs).",
        )
        return 1

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
