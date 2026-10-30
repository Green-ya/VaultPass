"""Настройка логирования VaultPass.

Технические детали (стек вызовов, ответы Vault) пишем в файл с ротацией,
а пользователю показываем только понятный текст. Секреты в лог не попадают:
логируем пути и типы ошибок, но не значения ключей.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / ".config" / "vaultpass"
LOG_FILE = LOG_DIR / "vaultpass.log"

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

MAX_BYTES = 1_000_000
BACKUP_COUNT = 3


def _make_file_handler(level: int):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(LOG_DIR, 0o700)
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        # Файл лога не критичен: при ошибке логируем только в консоль.
        return None

    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def _make_console_handler(level: int) -> logging.Handler:
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def setup_logging(debug: bool = False) -> logging.Logger:
    """Инициализирует корневой логгер (файл + консоль).

    Безопасно вызывать повторно: прежние обработчики снимаются.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # Корень пропускает всё, а детализацию ограничивают обработчики.
    root.setLevel(logging.DEBUG)

    file_handler = _make_file_handler(logging.DEBUG if debug else logging.INFO)
    if file_handler is not None:
        root.addHandler(file_handler)
    root.addHandler(
        _make_console_handler(logging.DEBUG if debug else logging.WARNING)
    )
    return root


def set_debug(debug: bool):
    """Переключает детализацию логов на лету (пункт меню «Режим отладки»)."""
    root = logging.getLogger()
    file_level = logging.DEBUG if debug else logging.INFO
    console_level = logging.DEBUG if debug else logging.WARNING

    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            handler.setLevel(file_level)
        else:
            handler.setLevel(console_level)
