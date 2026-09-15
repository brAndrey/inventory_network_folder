"""Чтение и разбор конфигурационного INI-файла.

Формат файла ``config.ini`` описан в README. Ключевая особенность — секция
``[ROOTS]`` хранит пары ``адрес;глубина``, где глубина индивидуальна для
каждого корня и может отсутствовать.
"""

from __future__ import annotations

import configparser
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import MonitorPaths, RootConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_NAME = "config.ini"
DEFAULT_DEPTH = -1


class ConfigLoader:
    """Поиск и разбор ``config.ini`` рядом со скриптом."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).resolve()
        self.config_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # Поиск файла
    # ------------------------------------------------------------------
    def find_config_path(self) -> Path:
        """Возвращает путь к конфигурационному файлу.

        Порядок поиска:
        1. Первый аргумент командной строки (файл или папка с INI).
        2. ``config.ini`` рядом со скриптом.
        """
        if len(sys.argv) > 1:
            arg = Path(sys.argv[1].strip('"'))
            if not arg.is_absolute():
                arg = self.base_dir / arg
            if arg.is_file():
                return arg
            if arg.is_dir():
                candidates = sorted(arg.glob("*.ini"))
                if candidates:
                    return candidates[0]
            raise FileNotFoundError(
                f"INI-файл из командной строки не найден: {sys.argv[1]}"
            )

        path = self.base_dir / DEFAULT_CONFIG_NAME
        if path.is_file():
            return path

        raise FileNotFoundError(
            f"Рядом со скриптом не найден {DEFAULT_CONFIG_NAME}. "
            f"Папка: {self.base_dir}"
        )

    # ------------------------------------------------------------------
    # Загрузка
    # ------------------------------------------------------------------
    def load(
        self,
        config_path: Optional[Path] = None,
    ) -> Tuple[List[RootConfig], Dict[str, str]]:
        """Читает конфиг и возвращает корни и опции.

        Возвращает кортеж ``(roots, options)``, где ``roots`` — список
        ``RootConfig``, а ``options`` — сырые строки из секции ``[OPTIONS]``.

        Если ``config_path`` не задан, файл ищется через :meth:`find_config_path`.
        """
        if config_path is None:
            self.config_path = self.find_config_path()
        else:
            self.config_path = Path(config_path)

        parser = configparser.RawConfigParser(strict=False, inline_comment_prefixes=None)
        parser.optionxform = str

        text = self._read_text(self.config_path)
        parser.read_string(text)

        roots = self._parse_roots(parser)
        options = self._parse_options(parser)

        return roots, options

    def load_alerts(self) -> Dict[str, str]:
        """Возвращает опции секции ``[ALERTS]`` (может отсутствовать)."""
        if self.config_path is None:
            self.config_path = self.find_config_path()

        parser = configparser.RawConfigParser(strict=False, inline_comment_prefixes=None)
        parser.optionxform = str
        parser.read_string(self._read_text(self.config_path))

        alerts: Dict[str, str] = {}
        for section in parser.sections():
            if section.strip().lower() == "alerts":
                for key, value in parser.items(section):
                    alerts[key.strip().lower()] = value
        return alerts

    def get_config_snapshot(self) -> str:
        """Возвращает полный текст конфига для аудита (config_snapshot)."""
        if self.config_path is None:
            self.config_path = self.find_config_path()
        return self._read_text(self.config_path)

    # ------------------------------------------------------------------
    # Разбор секций
    # ------------------------------------------------------------------
    def _parse_roots(self, parser: configparser.RawConfigParser) -> List[RootConfig]:
        """Собирает корни из секции ``[ROOTS]``."""
        roots: List[RootConfig] = []

        for section in parser.sections():
            if section.strip().lower() != "roots":
                continue
            for _, value in parser.items(section):
                root = self._parse_root_line(value)
                if root is not None:
                    roots.append(root)

        return roots

    def _parse_options(self, parser: configparser.RawConfigParser) -> Dict[str, str]:
        """Собирает опции из секции ``[OPTIONS]``."""
        options: Dict[str, str] = {}

        for section in parser.sections():
            if section.strip().lower() != "options":
                continue
            for key, value in parser.items(section):
                options[key.strip().lower()] = value

        return options

    # ------------------------------------------------------------------
    # Разбор строки корня
    # ------------------------------------------------------------------
    def _parse_root_line(self, line: str) -> Optional[RootConfig]:
        """Разбирает строку вида ``\\\\server\\share;3``.

        Правила:
        - ``path;depth`` -> ``path`` и ``depth``;
        - ``path`` без ``;`` -> глубина ``-1`` (без ограничения);
        - пробелы вокруг ``;`` игнорируются;
        - если после ``;`` не число — логируется ошибка, глубина ``-1``.
        """
        raw = str(line or "").strip().strip('"')
        if not raw:
            return None

        path_part = raw
        depth_part = ""

        if ";" in raw:
            path_part, depth_part = raw.rsplit(";", 1)
            path_part = path_part.strip().strip('"')
            depth_part = depth_part.strip()

        path_part = os.path.expandvars(os.path.expanduser(path_part))

        if not os.path.isabs(path_part):
            path_part = str((self.base_dir / path_part).resolve())

        path_part = os.path.normpath(path_part)

        if depth_part == "":
            depth = DEFAULT_DEPTH
        else:
            depth = self.parse_int(depth_part, default=DEFAULT_DEPTH)
            if not self._is_int(depth_part):
                logger.error(
                    "Некорректная глубина '%s' для корня '%s'. "
                    "Используется глубина -1 (без ограничения).",
                    depth_part,
                    path_part,
                )

        return RootConfig(path=path_part, max_depth=depth)

    @staticmethod
    def _is_int(value: str) -> bool:
        try:
            int(str(value).strip())
            return True
        except (TypeError, ValueError):
            return False

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------
    def _read_text(self, config_path: Path) -> str:
        """Читает текст INI, пробуя несколько кодировок."""
        last_error: Optional[Exception] = None

        for enc in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
            try:
                return Path(config_path).read_text(encoding=enc)
            except UnicodeDecodeError as exc:
                last_error = exc
                continue

        raise ValueError(f"Не удалось определить кодировку INI-файла: {last_error}")

    # ------------------------------------------------------------------
    # Статические парсеры значений
    # ------------------------------------------------------------------
    @staticmethod
    def parse_bool(value, default: bool = False) -> bool:
        """Преобразует строку в ``bool``; при ошибке возвращает ``default``."""
        if value is None:
            return default

        text = str(value).strip().lower()

        if text in {"1", "true", "yes", "on", "y", "t", "да", "истина"}:
            return True

        if text in {"0", "false", "no", "off", "n", "f", "нет", "ложь"}:
            return False

        return default

    @staticmethod
    def parse_int(value, default: int = 0) -> int:
        """Преобразует строку в ``int``; при ошибке возвращает ``default``."""
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default


def build_paths(base_dir: Path, options: Dict[str, str]) -> MonitorPaths:
    """Строит ``MonitorPaths`` из каталога скрипта и опций конфига.

    Относительные пути в опциях интерпретируются относительно ``base_dir``.
    """
    base_dir = Path(base_dir).resolve()

    def resolve(value: str, default: str) -> Path:
        raw = str(value).strip() or default
        path = Path(raw)
        if not path.is_absolute():
            path = base_dir / path
        return path

    return MonitorPaths(
        base_dir=base_dir,
        db_path=resolve(options.get("db_path", "folder_monitor.db"), "folder_monitor.db"),
        log_dir=resolve(options.get("log_dir", "Log"), "Log"),
        report_dir=resolve(options.get("report_dir", "Reports"), "Reports"),
    )
