"""Обход папок и подсчёт файлов без обращения к метаданным файлов.

Ключевое требование производительности: для каждой папки используется только
``os.scandir()`` и ``entry.is_file(follow_symlinks=False)``. Методы
``entry.stat()``, ``os.path.getsize()`` и ``os.path.getmtime()`` не вызываются
ни при каких обстоятельствах.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import FolderRecord, RootConfig, ScanError, ScanResult

# Системные/служебные файлы, которые пропускаются при count_hidden_files=false.
HIDDEN_SYSTEM_FILES = {"desktop.ini", "thumbs.db", ".ds_store"}


class ScanTimeoutError(Exception):
    """Сканирование превысило отведённое время.

    Атрибут ``partial_result`` содержит данные, собранные до прерывания.
    """

    def __init__(self, message: str, partial_result: Optional[ScanResult] = None):
        super().__init__(message)
        self.partial_result = partial_result


class FolderScanner:
    """Обходит корни с индивидуальной глубиной и считает файлы в папках."""

    def __init__(self, options: Dict, logger: logging.Logger):
        self.options = options
        self.logger = logger
        self.count_hidden_files = bool(options.get("count_hidden_files", True))

    # ------------------------------------------------------------------
    # Обход корня
    # ------------------------------------------------------------------
    def scan_root(
        self,
        root_config: RootConfig,
        scan_id: int,
        deadline: Optional[float] = None,
    ) -> ScanResult:
        """Сканирует один корень.

        ``deadline`` — значение ``time.monotonic()``, после которого сканирование
        прерывается исключением :class:`ScanTimeoutError`.
        """
        root = os.path.normpath(root_config.path)
        max_depth = root_config.max_depth

        folders: List[FolderRecord] = []
        errors: List[ScanError] = []
        total_file_count = 0

        if not os.path.exists(root):
            msg = "Путь не найден"
            errors.append(ScanError(root, msg))
            self.logger.error(f"{msg}: {root}")
            return ScanResult(folders, errors, 0, 0)

        if not os.path.isdir(root):
            msg = "Путь не является папкой"
            errors.append(ScanError(root, msg))
            self.logger.error(f"{msg}: {root}")
            return ScanResult(folders, errors, 0, 0)

        def onerror(os_error: OSError) -> None:
            path = getattr(os_error, "filename", root)
            message = f"{type(os_error).__name__}: {os_error}"
            errors.append(ScanError(path, message))
            self.logger.warning(f"Ошибка при сканировании: {message} | path: {path}")

        try:
            for dirpath, dirnames, _filenames in os.walk(
                root,
                topdown=True,
                onerror=onerror,
                followlinks=False,
            ):
                if deadline is not None and time.monotonic() > deadline:
                    raise ScanTimeoutError(
                        "Превышено время сканирования",
                        ScanResult(folders, errors, total_file_count, len(folders)),
                    )

                rel = self._relative_path(dirpath, root)
                level = self._level(dirpath, root)

                try:
                    file_count, file_names = self._count_files(dirpath)
                except OSError as exc:
                    message = f"{type(exc).__name__}: {exc}"
                    errors.append(ScanError(dirpath, message))
                    self.logger.warning(f"Ошибка чтения папки: {dirpath} ({message})")
                    file_count, file_names = 0, []

                folder_name = self._folder_name(dirpath)
                content_hash = self._compute_content_hash(file_names)

                folders.append(
                    FolderRecord(
                        scan_id=scan_id,
                        root=root,
                        relative_path=rel,
                        folder_name=folder_name,
                        level=level,
                        file_count=file_count,
                        max_depth=max_depth,
                        content_hash=content_hash,
                    )
                )
                total_file_count += file_count

                # Ограничение глубины на этапе обхода (не заходим глубже).
                if max_depth >= 0 and level >= max_depth:
                    dirnames.clear()

        except ScanTimeoutError:
            raise

        return ScanResult(
            folders=folders,
            errors=errors,
            total_file_count=total_file_count,
            folder_count=len(folders),
        )

    # ------------------------------------------------------------------
    # Подсчёт файлов
    # ------------------------------------------------------------------
    def _count_files(self, dirpath: str) -> Tuple[int, List[str]]:
        """Возвращает (количество файлов, имена файлов) в папке.

        Только ``os.scandir()`` и ``entry.is_file(follow_symlinks=False)``.
        Никаких ``stat()``, ``getsize()`` или чтения метаданных.
        """
        count = 0
        names: List[str] = []

        with os.scandir(dirpath) as it:
            for entry in it:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    # Запись стала недоступна между листингом и проверкой.
                    continue

                name = entry.name
                if not self.count_hidden_files and self._is_hidden(name):
                    continue

                count += 1
                names.append(name)

        return count, names

    @staticmethod
    def _is_hidden(name: str) -> bool:
        """Определяет, является ли файл скрытым/служебным."""
        if name.startswith("."):
            return True
        return name.lower() in HIDDEN_SYSTEM_FILES

    @staticmethod
    def _compute_content_hash(file_names: List[str]) -> str:
        """SHA-256 от сортированного списка имён файлов (без размеров)."""
        sorted_names = sorted(file_names)
        combined = "\n".join(sorted_names)
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------
    @staticmethod
    def _relative_path(dirpath: str, root: str) -> str:
        """Относительный путь с разделителем '/' (для корня — пустая строка)."""
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            return ""
        return rel.replace(os.sep, "/")

    @staticmethod
    def _level(dirpath: str, root: str) -> int:
        """Уровень вложенности относительно корня (корень = 0)."""
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            return 0
        return rel.replace(os.sep, "/").count("/") + 1

    @staticmethod
    def _folder_name(dirpath: str) -> str:
        """Имя папки (последний элемент пути)."""
        name = os.path.basename(os.path.normpath(dirpath))
        return name if name else os.path.normpath(dirpath)
