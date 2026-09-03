from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config_loader import InventoryPaths


class LoggerFactory:
    """
    Класс для создания логгера.

    Лог пишется:
    - в консоль, если есть stderr;
    - в файл Log/logs.

    Используется ротация логов:
    - основной файл logs;
    - резервные копии logs.1 ... logs.5.
    """

    def __init__(self, paths: InventoryPaths):
        self.paths = paths

    def create_logger(self, name: str = "inventory_folders") -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)

        if logger.handlers:
            return logger

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Консольный вывод добавляем только если есть stderr.
        # Это полезно, если скрипт запускается через pythonw или скрыто.
        if sys.stderr is not None:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        try:
            self.paths.log_dir.mkdir(parents=True, exist_ok=True)

            file_handler = RotatingFileHandler(
                self.paths.log_file,
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        except Exception as exc:
            # Если файловый лог создать не удалось, оставляем хотя бы консольный.
            logger.warning(
                f"Не удалось создать файл лога {self.paths.log_file}: {exc}. "
                "Лог будет только в консоли."
            )

        return logger