"""Слой работы с SQLite: схема БД и репозитории.

Всё взаимодействие с базой выполняется через ``DatabaseManager`` и тонкие
репозитории. Соединение открывается один раз на всё время работы приложения
и работает в режиме WAL. Все запросы параметризованы.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from models import FolderRecord, ScanError, now_str

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scans (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    status           TEXT NOT NULL DEFAULT 'running',
    folder_count     INTEGER DEFAULT 0,
    total_file_count INTEGER DEFAULT 0,
    config_snapshot  TEXT
);

CREATE TABLE IF NOT EXISTS folders (
    scan_id        INTEGER NOT NULL,
    root           TEXT NOT NULL,
    relative_path  TEXT NOT NULL,
    folder_name    TEXT NOT NULL,
    level          INTEGER NOT NULL,
    file_count     INTEGER NOT NULL DEFAULT 0,
    max_depth      INTEGER NOT NULL,
    content_hash   TEXT,
    PRIMARY KEY (scan_id, root, relative_path),
    FOREIGN KEY (scan_id) REFERENCES scans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER,
    timestamp   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    root        TEXT,
    old_path    TEXT,
    new_path    TEXT,
    details     TEXT,
    FOREIGN KEY (scan_id) REFERENCES scans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS scan_errors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id   INTEGER NOT NULL,
    path      TEXT NOT NULL,
    error     TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (scan_id) REFERENCES scans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS moves (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at       TEXT NOT NULL,
    scan_id           INTEGER NOT NULL,
    root              TEXT NOT NULL,
    old_relative_path TEXT NOT NULL,
    new_relative_path TEXT NOT NULL,
    folder_name       TEXT NOT NULL,
    confidence        TEXT NOT NULL,
    file_count        INTEGER,
    FOREIGN KEY (scan_id) REFERENCES scans(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_folders_scan_root ON folders(scan_id, root);
CREATE INDEX IF NOT EXISTS idx_folders_relpath ON folders(relative_path);
CREATE INDEX IF NOT EXISTS idx_folders_name ON folders(folder_name);
CREATE INDEX IF NOT EXISTS idx_folders_hash ON folders(content_hash);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_scan_errors_scan ON scan_errors(scan_id);
CREATE INDEX IF NOT EXISTS idx_moves_scan ON moves(scan_id);
CREATE INDEX IF NOT EXISTS idx_moves_detected ON moves(detected_at);
"""


class DatabaseManager:
    """Управляет единственным соединением с SQLite."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def get_connection(self) -> sqlite3.Connection:
        """Открывает (один раз) и возвращает соединение в режиме WAL."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def create_schema(self) -> None:
        """Создаёт таблицы и индексы (идемпотентно)."""
        conn = self.get_connection()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    def close(self) -> None:
        """Закрывает соединение, если оно было открыто."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def vacuum(self) -> None:
        """Сжимает файл базы данных."""
        conn = self.get_connection()
        conn.execute("VACUUM;")
        conn.commit()


class ScanRepository:
    """Работа с таблицей ``scans``."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def start_scan(self, config_snapshot: Optional[str]) -> int:
        """Создаёт запись скана со статусом 'running' и возвращает id."""
        conn = self.db.get_connection()
        cur = conn.execute(
            "INSERT INTO scans (started_at, status, config_snapshot) "
            "VALUES (?, 'running', ?)",
            (now_str(), config_snapshot),
        )
        conn.commit()
        return int(cur.lastrowid)

    def finish_scan(
        self,
        scan_id: int,
        status: str,
        folder_count: int,
        total_file_count: int,
    ) -> None:
        """Фиксирует завершение скана (completed/failed/timeout)."""
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE scans SET finished_at = ?, status = ?, folder_count = ?, "
            "total_file_count = ? WHERE id = ?",
            (now_str(), status, folder_count, total_file_count, scan_id),
        )
        conn.commit()

    def get_last_completed_scan(self) -> Optional[int]:
        """Возвращает id последнего завершённого скана (или None)."""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT id FROM scans WHERE status = 'completed' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None

    def get_previous_completed_scan(self, scan_id: int) -> Optional[int]:
        """Возвращает id предыдущего завершённого скана (id < scan_id)."""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT id FROM scans WHERE status = 'completed' AND id < ? "
            "ORDER BY id DESC LIMIT 1",
            (scan_id,),
        ).fetchone()
        return int(row["id"]) if row else None

    def get_scan_info(self, scan_id: int) -> Optional[sqlite3.Row]:
        """Возвращает строку скана или None."""
        conn = self.db.get_connection()
        return conn.execute(
            "SELECT * FROM scans WHERE id = ?", (scan_id,)
        ).fetchone()

    def get_running_scans(self) -> List[int]:
        """Возвращает id всех сканов со статусом 'running'."""
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT id FROM scans WHERE status = 'running' ORDER BY id"
        ).fetchall()
        return [int(r["id"]) for r in rows]

    def get_running_scans_older_than(self, hours: int) -> List[int]:
        """Возвращает id 'running'-сканов старше ``hours`` часов.

        Сравнение по строковому ``started_at`` формата ``YYYY-MM-DD HH:MM:SS``
        корректно, так как этот формат сортируется лексикографически.
        """
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT id, started_at FROM scans WHERE status = 'running'"
        ).fetchall()

        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(hours=hours)
        result: List[int] = []
        for row in rows:
            try:
                started = datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                continue
            if started < cutoff:
                result.append(int(row["id"]))
        return result


class FolderRepository:
    """Работа с таблицей ``folders``."""

    BATCH_SIZE = 1000

    def __init__(self, db: DatabaseManager):
        self.db = db

    def insert_folders_batch(
        self,
        scan_id: int,
        folders: List[FolderRecord],
    ) -> None:
        """Пакетная вставка папок через ``executemany`` по 1000 записей."""
        if not folders:
            return

        conn = self.db.get_connection()
        sql = (
            "INSERT OR REPLACE INTO folders "
            "(scan_id, root, relative_path, folder_name, level, file_count, "
            " max_depth, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )

        rows = [
            (
                f.scan_id,
                f.root,
                f.relative_path,
                f.folder_name,
                f.level,
                f.file_count,
                f.max_depth,
                f.content_hash,
            )
            for f in folders
        ]

        for start in range(0, len(rows), self.BATCH_SIZE):
            conn.executemany(sql, rows[start:start + self.BATCH_SIZE])

        conn.commit()

    def get_folders_by_scan(self, scan_id: int) -> List[FolderRecord]:
        """Возвращает все папки скана."""
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM folders WHERE scan_id = ? ORDER BY root, relative_path",
            (scan_id,),
        ).fetchall()

        return [
            FolderRecord(
                scan_id=int(r["scan_id"]),
                root=r["root"],
                relative_path=r["relative_path"],
                folder_name=r["folder_name"],
                level=int(r["level"]),
                file_count=int(r["file_count"]),
                max_depth=int(r["max_depth"]),
                content_hash=r["content_hash"],
            )
            for r in rows
        ]

    def get_folder_by_path(
        self,
        scan_id: int,
        root: str,
        relative_path: str,
    ) -> Optional[FolderRecord]:
        """Возвращает одну папку по ключу (scan_id, root, relative_path)."""
        conn = self.db.get_connection()
        row = conn.execute(
            "SELECT * FROM folders WHERE scan_id = ? AND root = ? "
            "AND relative_path = ?",
            (scan_id, root, relative_path),
        ).fetchone()

        if row is None:
            return None

        return FolderRecord(
            scan_id=int(row["scan_id"]),
            root=row["root"],
            relative_path=row["relative_path"],
            folder_name=row["folder_name"],
            level=int(row["level"]),
            file_count=int(row["file_count"]),
            max_depth=int(row["max_depth"]),
            content_hash=row["content_hash"],
        )


class EventRepository:
    """Работа с таблицей ``events``."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def add_event(
        self,
        scan_id: Optional[int],
        event_type: str,
        root: Optional[str] = None,
        old_path: Optional[str] = None,
        new_path: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        """Добавляет событие с текущей меткой времени."""
        conn = self.db.get_connection()
        conn.execute(
            "INSERT INTO events (scan_id, timestamp, event_type, root, "
            "old_path, new_path, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (scan_id, now_str(), event_type, root, old_path, new_path, details),
        )
        conn.commit()

    def get_events_by_type(
        self,
        event_type: str,
        since: Optional[str] = None,
    ) -> List[sqlite3.Row]:
        """Возвращает события заданного типа, опционально после ``since``."""
        conn = self.db.get_connection()
        if since is None:
            rows = conn.execute(
                "SELECT * FROM events WHERE event_type = ? ORDER BY timestamp",
                (event_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events WHERE event_type = ? AND timestamp >= ? "
                "ORDER BY timestamp",
                (event_type, since),
            ).fetchall()
        return rows


class ErrorRepository:
    """Работа с таблицей ``scan_errors``."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def add_error(self, scan_id: int, path: str, error: str) -> None:
        """Добавляет ошибку сканирования."""
        conn = self.db.get_connection()
        conn.execute(
            "INSERT INTO scan_errors (scan_id, path, error, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (scan_id, path, error, now_str()),
        )
        conn.commit()

    def get_errors_by_scan(self, scan_id: int) -> List[ScanError]:
        """Возвращает все ошибки скана."""
        conn = self.db.get_connection()
        rows = conn.execute(
            "SELECT * FROM scan_errors WHERE scan_id = ? ORDER BY id",
            (scan_id,),
        ).fetchall()

        return [
            ScanError(path=r["path"], error=r["error"], timestamp=r["timestamp"])
            for r in rows
        ]


class MoveRepository:
    """Работа с таблицей ``moves``."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def add_move(
        self,
        scan_id: int,
        root: str,
        old_path: str,
        new_path: str,
        folder_name: str,
        confidence: str,
        file_count: Optional[int],
    ) -> None:
        """Добавляет запись о перемещении папки."""
        conn = self.db.get_connection()
        conn.execute(
            "INSERT INTO moves (detected_at, scan_id, root, old_relative_path, "
            "new_relative_path, folder_name, confidence, file_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now_str(),
                scan_id,
                root,
                old_path,
                new_path,
                folder_name,
                confidence,
                file_count,
            ),
        )
        conn.commit()

    def get_moves_since(self, timestamp: str) -> List[sqlite3.Row]:
        """Возвращает перемещения, обнаруженные после ``timestamp``."""
        conn = self.db.get_connection()
        return conn.execute(
            "SELECT * FROM moves WHERE detected_at >= ? ORDER BY detected_at",
            (timestamp,),
        ).fetchall()


def delete_old_scans(db: DatabaseManager, retention_days: int) -> int:
    """Удаляет завершённые сканы старше ``retention_days`` дней.

    Связанные записи (folders, events, scan_errors, moves) удаляются каскадно
    благодаря ``ON DELETE CASCADE`` и включённому ``PRAGMA foreign_keys=ON``.
    Возвращает количество удалённых сканов.
    """
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = db.get_connection()
    cur = conn.execute(
        "DELETE FROM scans WHERE status != 'running' AND started_at < ?",
        (cutoff,),
    )
    conn.commit()
    return int(cur.rowcount)
