"""Тесты движка сравнения сканов (diff_engine)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from database import DatabaseManager, FolderRepository, ScanRepository
from diff_engine import DiffEngine
from models import FolderRecord


def _folder(scan_id, root, rel, name, level, count, hash_):
    return FolderRecord(
        scan_id=scan_id,
        root=root,
        relative_path=rel,
        folder_name=name,
        level=level,
        file_count=count,
        max_depth=-1,
        content_hash=hash_,
    )


def _hash(*names):
    return hashlib.sha256("\n".join(sorted(names)).encode("utf-8")).hexdigest()


def _setup_db():
    db = DatabaseManager(Path(":memory:"))
    db.create_schema()
    return db


def test_move_detection_high_confidence():
    db = _setup_db()
    scan_repo = ScanRepository(db)
    folder_repo = FolderRepository(db)

    old_id = scan_repo.start_scan(None)
    scan_repo.finish_scan(old_id, "completed", 0, 0)
    new_id = scan_repo.start_scan(None)
    scan_repo.finish_scan(new_id, "completed", 0, 0)

    root = r"\\server\share"
    content_b = _hash("file1.txt")

    folder_repo.insert_folders_batch(
        old_id,
        [
            _folder(old_id, root, "", "share", 0, 0, _hash()),
            _folder(old_id, root, "A", "A", 1, 0, _hash()),
            _folder(old_id, root, "A/B", "B", 2, 1, content_b),
        ],
    )
    folder_repo.insert_folders_batch(
        new_id,
        [
            _folder(new_id, root, "", "share", 0, 0, _hash()),
            _folder(new_id, root, "C", "C", 1, 0, _hash()),
            _folder(new_id, root, "C/B", "B", 2, 1, content_b),
        ],
    )

    diff = DiffEngine(db, logging.getLogger("test")).compare_scans(old_id, new_id)

    assert len(diff.moved) == 1
    move = diff.moved[0]
    assert move.folder_name == "B"
    assert move.old_path == "A/B"
    assert move.new_path == "C/B"
    assert move.confidence == "high"
    assert move.file_count == 1

    # Родительские папки A/C — отдельные удаление и создание.
    assert [f.folder_name for f in diff.deleted] == ["A"]
    assert [f.folder_name for f in diff.created] == ["C"]


def test_deletion_detection():
    db = _setup_db()
    scan_repo = ScanRepository(db)
    folder_repo = FolderRepository(db)

    old_id = scan_repo.start_scan(None)
    scan_repo.finish_scan(old_id, "completed", 0, 0)
    new_id = scan_repo.start_scan(None)
    scan_repo.finish_scan(new_id, "completed", 0, 0)

    root = r"\\server\share"
    folder_repo.insert_folders_batch(
        old_id,
        [
            _folder(old_id, root, "", "share", 0, 0, _hash()),
            _folder(old_id, root, "D", "D", 1, 5, _hash("a", "b")),
        ],
    )
    folder_repo.insert_folders_batch(
        new_id,
        [_folder(new_id, root, "", "share", 0, 0, _hash())],
    )

    diff = DiffEngine(db, logging.getLogger("test")).compare_scans(old_id, new_id)

    assert len(diff.deleted) == 1
    assert diff.deleted[0].folder_name == "D"
    assert diff.moved == []


def test_file_count_anomaly_requires_both_thresholds():
    root = r"\\server\share"

    def pair(old_count, new_count):
        old = _folder(1, root, "X", "X", 1, old_count, _hash("f"))
        new = _folder(2, root, "X", "X", 1, new_count, _hash("f"))
        return DiffEngine._find_file_count_anomalies([old], [new], 20.0, 10)

    # 100 -> 70: уменьшение на 30 (30% > 20% И 30 > 10) — аномалия.
    assert len(pair(100, 70)) == 1
    # 5 -> 0: уменьшение на 5 (100%, но < 10) — не аномалия.
    assert len(pair(5, 0)) == 0
    # 1000 -> 995: уменьшение на 5 (0.5%, < 20%) — не аномалия.
    assert len(pair(1000, 995)) == 0
    # Увеличение не является аномалией уменьшения.
    assert len(pair(10, 100)) == 0


def test_move_low_confidence_skipped_when_name_exists_unchanged():
    db = _setup_db()
    scan_repo = ScanRepository(db)
    folder_repo = FolderRepository(db)

    old_id = scan_repo.start_scan(None)
    scan_repo.finish_scan(old_id, "completed", 0, 0)
    new_id = scan_repo.start_scan(None)
    scan_repo.finish_scan(new_id, "completed", 0, 0)

    root = r"\\server\share"
    # В обоих сканах уже есть неизменённая папка с именем "B" (другое место).
    unchanged_b = _hash("stable.txt")

    folder_repo.insert_folders_batch(
        old_id,
        [
            _folder(old_id, root, "", "share", 0, 0, _hash()),
            _folder(old_id, root, "stable/B", "B", 2, 3, unchanged_b),
            _folder(old_id, root, "old/B", "B", 2, 10, _hash("moved.txt")),
        ],
    )
    folder_repo.insert_folders_batch(
        new_id,
        [
            _folder(new_id, root, "", "share", 0, 0, _hash()),
            _folder(new_id, root, "stable/B", "B", 2, 3, unchanged_b),
            _folder(new_id, root, "new/B", "B", 2, 10, _hash("moved.txt")),
        ],
    )

    # Хеш совпадает -> это medium/high, а не low, поэтому перемещение найдено.
    diff = DiffEngine(db, logging.getLogger("test")).compare_scans(old_id, new_id)
    assert len(diff.moved) == 1
    assert diff.moved[0].confidence == "high"
