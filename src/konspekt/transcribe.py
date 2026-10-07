"""Command-line entry point for audio transcription."""

from __future__ import annotations

import argparse
import sys

from .transcription import TranscriptionError, transcribe_audio


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Распознать речь из аудиофайла и вывести текст в терминал."
    )
    parser.add_argument("audio", help="Путь к аудиофайлу")
    parser.add_argument("--language", default="ru", help="Язык записи (по умолчанию: ru)")
    parser.add_argument("--prompt", help="Термины или контекст урока для подсказки модели")
    args = parser.parse_args()

    try:
        result = transcribe_audio(
            args.audio,
            language=args.language,
            prompt=args.prompt,
        )
    except TranscriptionError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1

    print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
