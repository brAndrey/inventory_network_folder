"""Тесты очистки старых сканов и защиты от параллельного запуска."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from cleanup import CleanupService
from database import (
    DatabaseManager,
    EventRepository,
    ScanRepository,
    delete_old_scans,
)
from main import MonitorApp


def _insert_scan_with_started_at(db, started_at, status="completed"):
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO scans (started_at, finished_at, status) VALUES (?, ?, ?)",
        (started_at, started_at, status),
    )
    conn.commit()
    return int(cur.lastrowid)


def test_delete_old_scans_removes_only_old(tmp_path):
    db = DatabaseManager(tmp_path / "test.db")
    db.create_schema()

    old_time = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    recent_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    old_id = _insert_scan_with_started_at(db, old_time)
    recent_id = _insert_scan_with_started_at(db, recent_time)

    removed = delete_old_scans(db, retention_days=7)

    assert removed == 1

    conn = db.get_connection()
    ids = {row["id"] for row in conn.execute("SELECT id FROM scans").fetchall()}
    assert old_id not in ids
    assert recent_id in ids

    db.close()


def test_delete_old_scans_cascades_to_folders(tmp_path):
    db = DatabaseManager(tmp_path / "test.db")
    db.create_schema()

    old_time = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    old_id = _insert_scan_with_started_at(db, old_time)

    conn = db.get_connection()
    conn.execute(
        "INSERT INTO folders (scan_id, root, relative_path, folder_name, level, "
        "file_count, max_depth, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (old_id, r"\\r", "x", "x", 1, 0, -1, "h"),
    )
    conn.commit()

    delete_old_scans(db, retention_days=7)

    remaining = conn.execute(
        "SELECT COUNT(*) AS c FROM folders WHERE scan_id = ?", (old_id,)
    ).fetchone()["c"]
    assert remaining == 0

    db.close()


def test_parallel_run_protection(tmp_path):
    app = MonitorApp()
    app.logger = logging.getLogger("test_parallel")

    db = DatabaseManager(tmp_path / "test.db")
    db.create_schema()
    app.db_manager = db
    app.scan_repo = ScanRepository(db)
    app.event_repo = EventRepository(db)

    # Без запущенных сканов новый запуск разрешён.
    assert app._check_duplicate_run() is False

    # Появился незавершённый (running) скан — новый запуск блокируется.
    app.scan_repo.start_scan(None)
    assert app._check_duplicate_run() is True

    db.close()


def test_running_scans_older_than(tmp_path):
    db = DatabaseManager(tmp_path / "test.db")
    db.create_schema()
    repo = ScanRepository(db)

    recent_id = repo.start_scan(None)
    stale_time = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    stale_id = _insert_scan_with_started_at(db, stale_time, status="running")

    assert recent_id in repo.get_running_scans()
    assert stale_id in repo.get_running_scans()
    assert stale_id in repo.get_running_scans_older_than(hours=2)
    assert recent_id not in repo.get_running_scans_older_than(hours=2)

    db.close()
