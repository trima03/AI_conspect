"""Record from the CLI; interactive Enter stops capture and saves the audio."""
from __future__ import annotations

import argparse
import sys
import threading

from .recording import RecordingError, list_input_devices, record_audio


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Записать звук с микрофона в WAV.")
    parser.add_argument("--devices", action="store_true", help="Показать микрофоны")
    parser.add_argument("--device", type=int, help="Номер микрофона")
    parser.add_argument("--seconds", type=float, help="Длительность; без параметра Enter завершает запись")
    args = parser.parse_args(argv)
    try:
        if args.devices:
            for index, name in list_input_devices():
                print(f"{index}: {name}")
            return 0
        stop = threading.Event()
        if args.seconds is None:
            if not sys.stdin.isatty():
                parser.error("Для неинтерактивного запуска задайте --seconds.")
            print("Запись начинается. Нажмите Enter, чтобы остановить и сохранить.", flush=True)
            def wait_for_enter():
                try:
                    input()
                finally:
                    stop.set()
            threading.Thread(target=wait_for_enter, daemon=True).start()
        result = []
        errors = []
        def capture():
            try:
                result.append(record_audio(stop, device=args.device, duration_seconds=args.seconds))
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=capture)
        thread.start()
        try:
            while thread.is_alive():
                thread.join(0.1)
        except KeyboardInterrupt:
            stop.set()
            thread.join()
        if errors:
            raise errors[0]
        print(f"Запись сохранена: {result[0]}")
        return 0
    except (RecordingError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
