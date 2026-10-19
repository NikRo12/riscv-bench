"""Мелкие общие функции: сообщения пользователю, остановка с ошибкой, хеш файла."""
import hashlib
import sys


def say(msg):
    """Заголовок этапа."""
    print(f"\n=== {msg}", flush=True)


def note(msg):
    """Обычная строка внутри этапа (с отступом)."""
    print(f"  {msg}", flush=True)


def die(msg):
    """Напечатать понятную ошибку и завершить скрипт с кодом 1."""
    print(f"\nОШИБКА: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256(path):
    """sha256 файла; читаем кусками по 1 МБ, чтобы большие файлы не занимали память."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
