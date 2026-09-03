from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from config_loader import ConfigLoader, InventoryPaths
from logger_setup import LoggerFactory
from scanner import FolderScanner


class InventoryApp:
    """
    Основной класс приложения.

    Связывает:
    - пути;
    - чтение конфига;
    - логирование;
    - сканирование;
    - запись CSV.
    """

    def __init__(self):
        self.paths = InventoryPaths(Path(__file__))
        self.config_loader = ConfigLoader(self.paths)
        self.logger = LoggerFactory(self.paths).create_logger()

    def run(self) -> int:
        self.logger.info("=== Начало инвентаризации структуры папок ===")

        # ------------------------------------------------------------
        # Поиск INI
        # ------------------------------------------------------------
        try:
            config_path = self.config_loader.find_config_path()
        except Exception as exc:
            self.logger.error(f"Не найден INI-файл: {exc}")
            return 1

        self.logger.info(f"Использован INI-файл: {config_path}")

        # ------------------------------------------------------------
        # Чтение настроек
        # ------------------------------------------------------------
        try:
            roots, raw_options = self.config_loader.load(config_path)
        except Exception as exc:
            self.logger.error(
                f"Ошибка чтения INI-файла {config_path}: {exc}"
            )
            return 2

        if not roots:
            self.logger.error(
                f"В INI-файле {config_path} не найдены адреса папок. "
                "Добавьте секцию [ROOTS] и значения с путями."
            )
            return 3

        self.logger.info(f"Найдено корневых папок: {len(roots)}")

        for root in roots:
            self.logger.info(f"Корень из INI: {root}")

        # ------------------------------------------------------------
        # Подготовка параметров
        # ------------------------------------------------------------
        options = self._prepare_options(raw_options)

        # ------------------------------------------------------------
        # Папка Report
        # ------------------------------------------------------------
        try:
            self.paths.report_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.error(
                f"Не удалось создать папку отчета {self.paths.report_dir}: {exc}"
            )
            return 4

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        csv_path = self.paths.report_dir / f"folders_chain_{timestamp}.csv"

        self.logger.info(f"CSV-файл отчета: {csv_path}")

        scanner = FolderScanner(options, self.logger)

        total_written = 0
        total_errors = 0

        # ------------------------------------------------------------
        # Сканирование и запись CSV
        # ------------------------------------------------------------
        try:
            with open(
                csv_path,
                "w",
                newline="",
                encoding=options["encoding"],
            ) as fh:
                writer = csv.writer(
                    fh,
                    delimiter=options["delimiter"],
                    quoting=csv.QUOTE_MINIMAL,
                    lineterminator="\n",
                )

                for root in roots:
                    self.logger.info(f"Сканирование корня: {root}")

                    written, errors = scanner.scan_root(root, writer)

                    total_written += written
                    total_errors += errors

                    self.logger.info(
                        f"Корень обработан: {root}. "
                        f"Записано папок: {written}. Ошибок: {errors}."
                    )

        except Exception as exc:
            self.logger.exception(f"Не удалось записать CSV: {exc}")
            return 5

        self.logger.info(
            f"Готово. Записано папок: {total_written}; "
            f"ошибок: {total_errors}; отчет: {csv_path}"
        )

        if total_errors:
            self.logger.warning(
                "Работа завершена с ошибками/предупреждениями. "
                "Подробности в логе."
            )

        return 0

    def _prepare_options(self, raw_options: Dict[str, str]) -> Dict[str, Any]:
        """
        Преобразует сырые строковые опции из INI
        в типизированные параметры для сканера.
        """
        encoding = str(raw_options.get("encoding", "utf-8-sig")).strip()
        if not encoding:
            encoding = "utf-8-sig"

        delimiter = ConfigLoader.parse_delimiter(
            raw_options.get("delimiter", ";")
        )

        root_label = str(raw_options.get("root_label", "name")).strip().lower()
        if root_label not in {"name", "path"}:
            root_label = "name"

        max_depth = ConfigLoader.parse_int(
            raw_options.get("max_depth", "0"),
            0,
        )

        if max_depth <= 0:
            max_depth = None

        return {
            "sort_dirs": ConfigLoader.parse_bool(
                raw_options.get("sort_dirs"),
                True,
            ),
            "follow_symlinks": ConfigLoader.parse_bool(
                raw_options.get("follow_symlinks"),
                False,
            ),
            "encoding": encoding,
            "delimiter": delimiter,
            "root_label": root_label,
            "max_depth": max_depth,
        }


def main() -> int:
    app = InventoryApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())