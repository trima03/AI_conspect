"""CLI for local lesson notes; no API key or external service."""
import argparse
import sqlite3
import sys
from pathlib import Path

from . import storage
from .notes import NotesError, NotesCancelled, generate_notes
from .pipeline import summarize_lesson


def main(argv=None):
    parser = argparse.ArgumentParser(description='Создать ИИ-конспект локально на Mac.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('transcript', nargs='?', type=Path, help='Текстовый файл UTF-8')
    source.add_argument('--lesson-id', type=int, help='Лекция в базе данных')
    parser.add_argument('--title', default='Лекция')
    parser.add_argument('--subject', default='')
    parser.add_argument('--style', choices=('short', 'detailed'), default='detailed')
    parser.add_argument('--output', type=Path, help='Новый файл Markdown; существующий не перезаписывается')
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error('Выходной файл уже существует. Укажите новое имя.')
    progress = lambda message: print(message, file=sys.stderr)
    try:
        if args.lesson_id is not None:
            storage.init_db()
            markdown = summarize_lesson(args.lesson_id, style=args.style, progress=progress).summary
        else:
            text = args.transcript.read_text(encoding='utf-8')
            markdown = generate_notes(text, title=args.title, subject=args.subject, style=args.style, progress=progress).markdown
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as output:
                output.write(markdown + '\n')
        print(markdown)
        return 0
    except (NotesCancelled, KeyboardInterrupt):
        print('Создание конспекта отменено.', file=sys.stderr)
        return 130
    except (NotesError, storage.StorageError, OSError, ValueError, sqlite3.Error) as error:
        print(f'Ошибка: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
