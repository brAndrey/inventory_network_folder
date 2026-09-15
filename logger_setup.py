"""Настройка логирования: консоль и файл с ротацией.

Лог пишется в ``<log_dir>/monitor.log`` с ротацией 5 файлов по 5 МБ.
Формат строки: ``2026-09-09 14:00:01 [INFO] Сообщение``.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_FILE_NAME = "monitor.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def setup_logger(log_dir: Path, log_file_name: str = LOG_FILE_NAME) -> logging.Logger:
    """Конфигурирует корневой логгер и возвращает его.

    Консольный обработчик добавляется, только если доступен ``sys.stderr``.
    Файловый обработчик добавляется с ротацией; при ошибке доступа к файлу
    лог остаётся только в консоли.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Убираем ранее добавленные обработчики, чтобы setup_logger был идемпотентным.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)

    if sys.stderr is not None:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    try:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_dir / log_file_name,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as exc:
        logger.warning(
            "Не удалось создать файл лога %s: %s. Лог будет только в консоли.",
            log_dir / log_file_name,
            exc,
        )

    return logger
