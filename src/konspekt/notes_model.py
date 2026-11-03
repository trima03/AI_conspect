"""Download pinned model weights in a cancellable child, using HTTP transport."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MODEL_ID = 'mlx-community/Qwen3-4B-Instruct-2507-4bit'
MODEL_REVISION = '50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b'
PATTERNS = ['*.json', '*.safetensors', '*.model', '*.jinja', 'merges.txt', 'vocab.json', 'tokenizer*']


def cache_dir():
    return Path.home() / '.cache/konspekt/notes-http'


def _valid(path):
    if not all((path/name).is_file() for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json')):
        return False
    index = path/'model.safetensors.index.json'
    if index.is_file():
        weights = set(json.loads(index.read_text())['weight_map'].values())
        return bool(weights) and all((path/name).is_file() for name in weights)
    return any(path.glob('*.safetensors'))


def _cached():
    path = cache_dir() / ('models--' + MODEL_ID.replace('/', '--')) / 'snapshots' / MODEL_REVISION
    return path if path.is_dir() and _valid(path) else None


def ensure_model(cancel_event, report):
    from .notes import NotesError, _check_cancel
    _check_cancel(cancel_event)
    ready = _cached()
    if ready:
        return str(ready)
    env = dict(os.environ, HF_HUB_DISABLE_XET='1', HF_HUB_DOWNLOAD_TIMEOUT='60')
    report('Скачивание модели конспектов (~2,3 ГБ). Это требуется один раз…')
    with tempfile.TemporaryFile() as output:
        with subprocess.Popen([sys.executable, '-m', 'konspekt.notes_model'], env=env,
                              stdout=output, stderr=output) as process:
            try:
                while process.poll() is None:
                    _check_cancel(cancel_event)
                    time.sleep(.2)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
    _check_cancel(cancel_event)
    ready = _cached()
    if process.returncode or ready is None:
        raise NotesError('Не удалось скачать модель конспектов. Проверьте интернет и повторите; загрузка продолжится из кэша.')
    return str(ready)


if __name__ == '__main__':
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_ID, revision=MODEL_REVISION, cache_dir=cache_dir(),
                      allow_patterns=PATTERNS, max_workers=2)
