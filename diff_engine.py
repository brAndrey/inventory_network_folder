"""Сравнение двух сканов и детекция перемещений папок.

Перемещения ищутся жадным сопоставлением в три прохода по уровню уверенности:
``high`` -> ``medium`` -> ``low``. Одна исчезнувшая папка может быть сопоставлена
только одной появившейся, и наоборот.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from database import DatabaseManager, FolderRepository
from models import (
    DiffResult,
    FolderAnomaly,
    FolderRecord,
    Move,
)

DEFAULT_DECREASE_PERCENT = 20.0
DEFAULT_DECREASE_MIN = 10


class DiffEngine:
    """Сравнивает два скана и формирует :class:`DiffResult`."""

    def __init__(self, db_manager: DatabaseManager, logger: logging.Logger):
        self.db_manager = db_manager
        self.logger = logger
        self.folder_repo = FolderRepository(db_manager)

    def compare_scans(
        self,
        old_scan_id: int,
        new_scan_id: int,
        options: Optional[Dict] = None,
    ) -> DiffResult:
        """Сравнивает старый и новый сканы.

        ``options`` может содержать ``file_count_decrease_percent`` и
        ``file_count_decrease_min``.
        """
        options = options or {}
        old_folders = self.folder_repo.get_folders_by_scan(old_scan_id)
        new_folders = self.folder_repo.get_folders_by_scan(new_scan_id)

        old_index = {(f.root, f.relative_path): f for f in old_folders}
        new_index = {(f.root, f.relative_path): f for f in new_folders}

        deleted = [f for f in old_folders if (f.root, f.relative_path) not in new_index]
        created = [f for f in new_folders if (f.root, f.relative_path) not in old_index]

        moves, remaining_deleted, remaining_created = self._match_moves(
            deleted, created, old_folders, new_folders
        )

        anomalies = self._find_file_count_anomalies(
            old_folders,
            new_folders,
            float(options.get("file_count_decrease_percent", DEFAULT_DECREASE_PERCENT)),
            int(options.get("file_count_decrease_min", DEFAULT_DECREASE_MIN)),
        )

        return DiffResult(
            created=remaining_created,
            deleted=remaining_deleted,
            moved=moves,
            file_count_decreased=anomalies,
        )

    # ------------------------------------------------------------------
    # Исчезнувшие / появившиеся
    # ------------------------------------------------------------------
    @staticmethod
    def _find_deleted_folders(
        old_folders: List[FolderRecord],
        new_folders: List[FolderRecord],
    ) -> List[FolderRecord]:
        """Папки, которые были в старом скане, но отсутствуют в новом."""
        new_keys = {(f.root, f.relative_path) for f in new_folders}
        return [f for f in old_folders if (f.root, f.relative_path) not in new_keys]

    @staticmethod
    def _find_created_folders(
        old_folders: List[FolderRecord],
        new_folders: List[FolderRecord],
    ) -> List[FolderRecord]:
        """Папки, которые есть в новом скане, но отсутствовали в старом."""
        old_keys = {(f.root, f.relative_path) for f in old_folders}
        return [f for f in new_folders if (f.root, f.relative_path) not in old_keys]

    # ------------------------------------------------------------------
    # Сопоставление перемещений
    # ------------------------------------------------------------------
    def _match_moves(
        self,
        deleted: List[FolderRecord],
        created: List[FolderRecord],
        old_folders: List[FolderRecord],
        new_folders: List[FolderRecord],
    ) -> Tuple[List[Move], List[FolderRecord], List[FolderRecord]]:
        """Сопоставляет исчезнувшие и появившиеся папки.

        Возвращает ``(moves, remaining_deleted, remaining_created)``.
        Сопоставление выполняется только внутри одного корня.
        """
        moves: List[Move] = []

        new_keys = {(f.root, f.relative_path) for f in new_folders}
        # Неизменённые папки (существуют в обоих сканах по тому же ключу).
        unchanged_names_by_root: Dict[str, Set[str]] = defaultdict(set)
        for f in old_folders:
            if (f.root, f.relative_path) in new_keys:
                unchanged_names_by_root[f.root].add(f.folder_name)

        deleted_by_root: Dict[str, List[FolderRecord]] = defaultdict(list)
        created_by_root: Dict[str, List[FolderRecord]] = defaultdict(list)
        for f in deleted:
            deleted_by_root[f.root].append(f)
        for f in created:
            created_by_root[f.root].append(f)

        remaining_deleted: List[FolderRecord] = []
        remaining_created: List[FolderRecord] = []

        all_roots = set(deleted_by_root) | set(created_by_root)
        for root in all_roots:
            d_list = list(deleted_by_root.get(root, []))
            c_list = list(created_by_root.get(root, []))
            unchanged_names = unchanged_names_by_root.get(root, set())

            d_left, c_left, root_moves = self._greedy_match(
                d_list, c_list, unchanged_names
            )
            moves.extend(root_moves)
            remaining_deleted.extend(d_left)
            remaining_created.extend(c_left)

        return moves, remaining_deleted, remaining_created

    def _greedy_match(
        self,
        deleted: List[FolderRecord],
        created: List[FolderRecord],
        unchanged_names: Set[str],
    ) -> Tuple[List[FolderRecord], List[FolderRecord], List[Move]]:
        """Жадное сопоставление по уровням high/medium/low."""
        moves: List[Move] = []
        deleted = list(deleted)
        created = list(created)

        matched_deleted: Set[int] = set()
        used_created: Set[int] = set()

        for confidence in ("high", "medium", "low"):
            for i, d in enumerate(deleted):
                if i in matched_deleted:
                    continue
                for j, c in enumerate(created):
                    if j in used_created:
                        continue
                    if self._match_move_candidate(d, c, unchanged_names) == confidence:
                        moves.append(
                            Move(
                                root=d.root,
                                old_path=d.relative_path,
                                new_path=c.relative_path,
                                folder_name=d.folder_name,
                                confidence=confidence,
                                file_count=c.file_count,
                            )
                        )
                        matched_deleted.add(i)
                        used_created.add(j)
                        break

        remaining_deleted = [
            d for i, d in enumerate(deleted) if i not in matched_deleted
        ]
        remaining_created = [
            c for j, c in enumerate(created) if j not in used_created
        ]
        return remaining_deleted, remaining_created, moves

    @staticmethod
    def _match_move_candidate(
        deleted_folder: FolderRecord,
        created_folder: FolderRecord,
        unchanged_names: Set[str],
    ) -> Optional[str]:
        """Возвращает уровень уверенности ('high'/'medium'/'low') или None."""
        if deleted_folder.folder_name != created_folder.folder_name:
            return None

        # high / medium — совпадает хеш содержимого.
        if deleted_folder.content_hash == created_folder.content_hash:
            if deleted_folder.file_count == created_folder.file_count:
                return "high"
            return "medium"

        # low — только имя, близкое количество файлов, и имя не встречается
        # среди неизменённых папок этого корня (чтобы не путать одноимённые).
        if deleted_folder.folder_name in unchanged_names:
            return None

        if DiffEngine._within_percent(
            deleted_folder.file_count, created_folder.file_count, 0.10
        ):
            return "low"

        return None

    @staticmethod
    def _within_percent(a: int, b: int, percent: float) -> bool:
        """Симметричная проверка: отличается ли ``a`` от ``b`` не более чем на
        ``percent`` (доля от единицы)."""
        if a == b:
            return True
        denom = max(abs(a), abs(b), 1)
        return abs(a - b) / denom <= percent

    # ------------------------------------------------------------------
    # Аномалии количества файлов
    # ------------------------------------------------------------------
    @staticmethod
    def _find_file_count_anomalies(
        old_folders: List[FolderRecord],
        new_folders: List[FolderRecord],
        decrease_percent: float,
        decrease_min: int,
    ) -> List[FolderAnomaly]:
        """Папки, в которых количество файлов уменьшилось аномально.

        Срабатывает только при одновременном выполнении обоих порогов:
        процентного и абсолютного.
        """
        new_index = {(f.root, f.relative_path): f for f in new_folders}
        anomalies: List[FolderAnomaly] = []

        for old in old_folders:
            new = new_index.get((old.root, old.relative_path))
            if new is None:
                continue

            if old.file_count > new.file_count:
                decrease = old.file_count - new.file_count
                percent = (
                    (decrease / old.file_count) * 100.0 if old.file_count > 0 else 0.0
                )
                if decrease > decrease_min and percent > decrease_percent:
                    anomalies.append(
                        FolderAnomaly(
                            root=old.root,
                            relative_path=old.relative_path,
                            folder_name=old.folder_name,
                            old_file_count=old.file_count,
                            new_file_count=new.file_count,
                            decrease_percent=percent,
                        )
                    )

        return anomalies
