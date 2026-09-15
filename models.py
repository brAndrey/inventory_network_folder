"""Dataclasses для передачи данных между модулями монитора папок.

Все классы данных, которыми обмениваются конфигурация, сканер, движок
сравнения, отчёты и слой работы с БД, собраны здесь, чтобы избежать
циклических импортов и держать структуры в одном месте.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def now_str() -> str:
    """Возвращает текущее локальное время в формате, пригодном для БД.

    Формат ``YYYY-MM-DD HH:MM:SS`` сортируется лексикографически так же,
    как и по времени, поэтому допустимо сравнивать такие строки напрямую.
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class MonitorPaths:
    """Пути, используемые приложением (рядом со скриптом)."""

    base_dir: Path
    db_path: Path
    log_dir: Path
    report_dir: Path


@dataclass
class RootConfig:
    """Один корень из конфигурации: адрес и индивидуальная глубина."""

    path: str
    max_depth: int


@dataclass
class FolderRecord:
    """Запись об одной папке внутри одного скана."""

    scan_id: int
    root: str
    relative_path: str
    folder_name: str
    level: int
    file_count: int
    max_depth: int
    content_hash: str


@dataclass
class ScanError:
    """Ошибка доступа/чтения отдельной папки или корня."""

    path: str
    error: str
    timestamp: Optional[str] = None


@dataclass
class ScanResult:
    """Результат сканирования одного корня."""

    folders: List[FolderRecord] = field(default_factory=list)
    errors: List[ScanError] = field(default_factory=list)
    total_file_count: int = 0
    folder_count: int = 0


@dataclass
class Move:
    """Обнаруженное перемещение папки между двумя сканами."""

    root: str
    old_path: str
    new_path: str
    folder_name: str
    confidence: str
    file_count: int


@dataclass
class FolderAnomaly:
    """Папка с аномальным уменьшением количества файлов."""

    root: str
    relative_path: str
    folder_name: str
    old_file_count: int
    new_file_count: int
    decrease_percent: float


@dataclass
class DiffResult:
    """Итог сравнения двух сканов."""

    created: List[FolderRecord] = field(default_factory=list)
    deleted: List[FolderRecord] = field(default_factory=list)
    moved: List[Move] = field(default_factory=list)
    file_count_decreased: List[FolderAnomaly] = field(default_factory=list)
