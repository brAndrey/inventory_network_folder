"""Очистка старых сканов и обслуживание базы данных."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from database import DatabaseManager, delete_old_scans


class CleanupService:
    """Удаляет устаревшие сканы и выполняет VACUUM не чаще раза в сутки."""

    VACUUM_MARKER_NAME = ".last_vacuum"

    def __init__(self, db_manager: DatabaseManager, logger: logging.Logger):
        self.db_manager = db_manager
        self.logger = logger
        self.vacuum_marker = Path(db_manager.db_path).with_name(self.VACUUM_MARKER_NAME)

    def delete_old_scans(self, retention_days: int) -> int:
        """Удаляет завершённые сканы старше ``retention_days`` дней."""
        count = delete_old_scans(self.db_manager, retention_days)
        if count:
            self.logger.info(f"Удалено старых сканов: {count}")
        return count

    def vacuum_database(self) -> None:
        """Выполняет VACUUM, если с прошлого раза прошло больше суток."""
        import time

        if not self._should_vacuum():
            return

        try:
            self.db_manager.vacuum()
            self.vacuum_marker.write_text(str(time.time()), encoding="utf-8")
            self.logger.info("Выполнен VACUUM базы данных.")
        except Exception as exc:
            self.logger.warning(f"Не удалось выполнить VACUUM: {exc}")

    def _should_vacuum(self) -> bool:
        """True, если маркер отсутствует или старше 24 часов."""
        import time

        if not self.vacuum_marker.exists():
            return True

        try:
            last = float(self.vacuum_marker.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            return True

        return (time.time() - last) >= 24 * 60 * 60
