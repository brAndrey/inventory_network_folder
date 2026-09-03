from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Tuple
import logging


class FolderScanner:
    """
    Класс для сканирования одной корневой папки.

    Формат строки CSV:
    корень;родительская папка1;родительская папка2;текущая папка

    Количество колонок переменное:
    корень + все родительские папки + текущая папка.
    """

    def __init__(self, options: Dict[str, Any], logger: logging.Logger):
        self.options = options
        self.logger = logger

    def scan_root(self, root: str, writer) -> Tuple[int, int]:
        """
        Обходит одну корневую папку.

        Возвращает:
        (
            количество записанных строк,
            количество ошибок
        )
        """
        root = os.path.normpath(root)

        root_label = self._get_root_label(root)

        max_depth = self.options.get("max_depth")
        follow_symlinks = self.options.get("follow_symlinks", False)
        sort_dirs = self.options.get("sort_dirs", True)

        if not os.path.exists(root):
            self.logger.error(
                f"Корневой путь не найден или нет доступа: {root}"
            )
            return 0, 1

        if not os.path.isdir(root):
            self.logger.error(
                f"Корневой путь не является папкой: {root}"
            )
            return 0, 1

        errors = 0
        written = 0

        # Записываем сам корень.
        try:
            writer.writerow([root_label])
            written += 1
            self.logger.info(f"Корень записан в CSV: {root_label}")
        except Exception as exc:
            self.logger.error(
                f"Не удалось записать корень {root_label}: {exc}"
            )
            return 0, 1

        def onerror(os_error):
            nonlocal errors
            errors += 1

            path = getattr(os_error, "filename", root)

            self.logger.warning(
                f"Ошибка при сканировании: "
                f"{type(os_error).__name__}: {os_error} | path: {path}"
            )

        for dirpath, dirnames, _ in os.walk(
            root,
            topdown=True,
            onerror=onerror,
            followlinks=follow_symlinks,
        ):
            if sort_dirs:
                dirnames.sort(key=lambda x: x.lower())

            try:
                rel = os.path.relpath(dirpath, root)
                level = 0 if rel == "." else len(Path(rel).parts)
            except ValueError as exc:
                errors += 1
                self.logger.warning(
                    f"Не удалось вычислить уровень вложенности: "
                    f"{dirpath}; {exc}"
                )
                continue

            # Сам корень уже записан выше, пропускаем его в цикле.
            if level == 0:
                if max_depth is not None and level >= max_depth:
                    dirnames.clear()
                continue

            if max_depth is not None and level > max_depth:
                dirnames.clear()
                continue

            try:
                row = [root_label] + list(Path(rel).parts)
                writer.writerow(row)
                written += 1
            except Exception as exc:
                errors += 1
                self.logger.error(
                    f"Не удалось записать строку CSV для {dirpath}: {exc}"
                )

            if max_depth is not None and level >= max_depth:
                dirnames.clear()

        return written, errors

    def _get_root_label(self, root: str) -> str:
        """
        Определяет, что писать в качестве корня в CSV.

        mode = "name" -> имя корневой папки;
        mode = "path" -> полный путь корня.
        """
        mode = str(self.options.get("root_label", "name")).strip().lower()

        if mode == "path":
            return os.path.normpath(root)

        return self._get_folder_name(root)

    @staticmethod
    def _get_folder_name(path: str) -> str:
        """
        Возвращает имя папки.
        Для корней вида C:\ или \\server\share возвращает осмысленный идентификатор.
        """
        path = os.path.normpath(path)
        name = os.path.basename(path)

        if name:
            return name

        return path