from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


class InventoryPaths:
    """
    Хранит пути, которые должны быть рядом со скриптом:
    - папку Report;
    - папку Log;
    - файл лога logs;
    - имена INI-файлов.
    """

    REPORT_DIR_NAME = "Report"
    LOG_DIR_NAME = "Log"

    # Если нужен файл логов с расширением, например logs.log,
    # поменяйте на LOG_FILE_NAME = "logs.log"
    LOG_FILE_NAME = "logs.log"

    DEFAULT_CONFIG_NAMES = (
        "folders.ini",
        "config.ini",
        "inventory.ini",
    )

    def __init__(self, base_file: Optional[Path] = None):
        """
        base_file - обычно путь к main.py.
        Если не передан, используется путь к текущему файлу.
        """
        if base_file is None:
            base_file = Path(__file__)

        base = Path(base_file).resolve()

        if base.is_dir():
            self.base_dir = base
        else:
            self.base_dir = base.parent

        self.report_dir = self.base_dir / self.REPORT_DIR_NAME
        self.log_dir = self.base_dir / self.LOG_DIR_NAME
        self.log_file = self.log_dir / self.LOG_FILE_NAME


class ConfigLoader:
    """
    Класс для поиска и чтения INI-файла.
    """

    ROOT_SECTIONS = {
        "roots",
        "root",
        "folders",
        "folder",
        "addresses",
        "address",
        "paths",
        "path",
    }

    def __init__(self, paths: InventoryPaths):
        self.paths = paths

    def find_config_path(self) -> Path:
        """
        Ищет INI рядом со скриптом.

        Порядок:
        1. Если передан аргумент командной строки, используем его.
        2. Ищем folders.ini, config.ini, inventory.ini рядом со скриптом.
        3. Если таких нет, берем первый найденный *.ini рядом со скриптом.
        """
        if len(sys.argv) > 1:
            arg = Path(sys.argv[1].strip('"'))

            if not arg.is_absolute():
                arg = self.paths.base_dir / arg

            if arg.is_file():
                return arg

            if arg.is_dir():
                candidates = sorted(arg.glob("*.ini"))
                if candidates:
                    return candidates[0]

            raise FileNotFoundError(
                f"INI-файл из командной строки не найден: {sys.argv[1]}"
            )

        for name in self.paths.DEFAULT_CONFIG_NAMES:
            path = self.paths.base_dir / name
            if path.is_file():
                return path

        candidates = sorted(self.paths.base_dir.glob("*.ini"))
        if candidates:
            return candidates[0]

        raise FileNotFoundError(
            f"Рядом со скриптом не найден INI-файл. "
            f"Папка: {self.paths.base_dir}. "
            f"Ожидалось одно из имен: {', '.join(self.paths.DEFAULT_CONFIG_NAMES)} "
            f"или любой файл *.ini."
        )

    def load(self, config_path: Path) -> Tuple[List[str], Dict[str, str]]:
        """
        Читает INI и возвращает:
        - список корневых папок;
        - словарь опций из секции [OPTIONS].
        """
        parser = configparser.RawConfigParser(strict=False)
        parser.optionxform = str

        text = self._read_text(config_path)
        parser.read_string(text)

        roots = self._collect_roots(parser)

        if not roots:
            roots = self._collect_roots_fallback(parser)

        roots = self._unique_roots(roots)
        options = self._collect_options(parser)

        return roots, options

    def _read_text(self, config_path: Path) -> str:
        """
        Читает текст INI, пробуя несколько кодировок.
        """
        last_error = None

        for enc in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
            try:
                return Path(config_path).read_text(encoding=enc)
            except UnicodeDecodeError as exc:
                last_error = exc
                continue

        raise ValueError(
            f"Не удалось определить кодировку INI-файла: {last_error}"
        )

    def _collect_roots(self, parser: configparser.RawConfigParser) -> List[str]:
        """
        Собирает корни из секций [ROOTS], [FOLDERS] и аналогичных.
        """
        roots = []

        for section in parser.sections():
            if section.strip().lower() in self.ROOT_SECTIONS:
                for _, value in parser.items(section):
                    for raw in self._iter_ini_lines(value):
                        path = self._expand_path(raw)
                        if path:
                            roots.append(path)

        return roots

    def _collect_roots_fallback(
        self,
        parser: configparser.RawConfigParser,
    ) -> List[str]:
        """
        Запасной вариант: если явной секции с путями нет,
        ищем абсолютные пути во всех секциях кроме OPTIONS.
        """
        roots = []

        for section in parser.sections():
            if section.strip().lower() == "options":
                continue

            for _, value in parser.items(section):
                for raw in self._iter_ini_lines(value):
                    if self._looks_like_path(raw):
                        path = self._expand_path(raw)
                        if path:
                            roots.append(path)

        return roots

    def _collect_options(
        self,
        parser: configparser.RawConfigParser,
    ) -> Dict[str, str]:
        """
        Собирает опции из секции [OPTIONS].
        """
        options = {}

        for section in parser.sections():
            if section.strip().lower() == "options":
                for key, value in parser.items(section):
                    options[key.strip().lower()] = value

        return options

    def _unique_roots(self, roots: List[str]) -> List[str]:
        """
        Убирает дубликаты корней, сохраняя порядок.
        """
        unique_roots = []
        seen = set()

        for root in roots:
            key = os.path.normcase(root)
            if key not in seen:
                seen.add(key)
                unique_roots.append(root)

        return unique_roots

    def _expand_path(self, raw: str) -> str:
        """
        Раскрывает переменные окружения и ~.
        Относительные пути считает относительно папки скрипта.
        """
        raw = str(raw or "").strip().strip('"')

        if not raw:
            return ""

        raw = os.path.expandvars(os.path.expanduser(raw))

        if not os.path.isabs(raw):
            raw = str((self.paths.base_dir / raw).resolve())

        return os.path.normpath(raw)

    @staticmethod
    def _iter_ini_lines(value: str) -> Iterable[str]:
        """
        Разбивает значение INI на строки.

        Это позволяет перечислять несколько путей в одном ключе:
        roots =
            \\server\share1
            \\server\share2
        """
        for line in str(value or "").splitlines():
            line = line.strip().strip('"')
            if line:
                yield line

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        """
        Проверяет, похоже ли значение на путь.
        """
        v = str(value or "").strip().strip('"')

        if not v:
            return False

        low = v.lower()

        if low in {
            "true",
            "false",
            "yes",
            "no",
            "on",
            "off",
            "1",
            "0",
        }:
            return False

        expanded = os.path.expandvars(os.path.expanduser(v))
        return os.path.isabs(expanded)

    @staticmethod
    def parse_bool(value, default=False) -> bool:
        if value is None:
            return default

        text = str(value).strip().lower()

        if text in {"1", "true", "yes", "on", "y", "t", "да", "истина"}:
            return True

        if text in {"0", "false", "no", "off", "n", "f", "нет", "ложь"}:
            return False

        return default

    @staticmethod
    def parse_int(value, default=0) -> int:
        try:
            return int(str(value).strip())
        except Exception:
            return default

    @staticmethod
    def parse_delimiter(value) -> str:
        """
        Поддерживает человекочитаемые значения:
        delimiter = semicolon
        delimiter = comma
        delimiter = tab
        """
        if value is None:
            return ";"

        text = str(value).strip()

        if not text:
            return ";"

        low = text.lower()

        if low in {"semicolon", ";"}:
            return ";"

        if low == "tab":
            return "\t"

        if low in {"comma", ","}:
            return ","

        return text[0]