"""Local transcription CLI: transcribe-lesson recording.m4a --model small."""
from __future__ import annotations

import argparse
import sys
import sqlite3
from pathlib import Path

from . import storage
from .transcription import TranscriptionError, DEFAULT_MODEL, transcribe_audio


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Бесплатно распознать аудио на компьютере.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("audio", nargs="?", help="Путь к аудиофайлу")
    source.add_argument("--lesson-id", type=int, help="Распознать и сохранить существующий урок")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--prompt", help="Термины и контекст урока")
    parser.add_argument("--model", choices=("turbo", "tiny", "small"), default=DEFAULT_MODEL)
    parser.add_argument("--backend", choices=("auto", "mlx", "cpu"), default="auto")
    parser.add_argument("--reduce-noise", action="store_true", help="Снизить постоянный фон и гул перед распознаванием; исходный файл не меняется")
    parser.add_argument("--output", type=Path, help="Сохранить текст в новый файл UTF-8")
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error("Выходной файл уже существует. Укажите новое имя, чтобы сохранить прежний текст.")
    try:
        options = dict(language=args.language, prompt=args.prompt, model=args.model, backend=args.backend,
                       progress=lambda message: print(message, file=sys.stderr), reduce_noise=args.reduce_noise)
        if args.lesson_id is not None:
            from .pipeline import transcribe_lesson
            text = transcribe_lesson(args.lesson_id, **options).transcript
        else:
            text = transcribe_audio(args.audio, **options).text
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as output:
                output.write(text + "\n")
            print(f"Текст сохранён: {args.output}", file=sys.stderr)
        print(text)
        return 0
    except KeyboardInterrupt:
        print("Обработка прервана.", file=sys.stderr)
        return 130
    except (TranscriptionError, storage.StorageError, OSError, sqlite3.Error) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
