import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS processed_files (
                        path         TEXT NOT NULL PRIMARY KEY,
                        mtime        REAL NOT NULL,
                        status       TEXT NOT NULL DEFAULT 'done',
                        processed_at TEXT NOT NULL,
                        error_msg    TEXT
                    )
                """)

    def is_processed(self, path: str, mtime: float) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status, mtime FROM processed_files WHERE path = ?",
                    (path,),
                ).fetchone()
        if row is None:
            return False
        return row['status'] == 'done' and abs(row['mtime'] - mtime) < 0.001

    def mark_done(self, path: str, mtime: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute("""
                    INSERT INTO processed_files (path, mtime, status, processed_at, error_msg)
                    VALUES (?, ?, 'done', ?, NULL)
                    ON CONFLICT(path) DO UPDATE SET
                        mtime        = excluded.mtime,
                        status       = 'done',
                        processed_at = excluded.processed_at,
                        error_msg    = NULL
                """, (path, mtime, now))

    def mark_failed(self, path: str, mtime: float, error: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute("""
                    INSERT INTO processed_files (path, mtime, status, processed_at, error_msg)
                    VALUES (?, ?, 'failed', ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        mtime        = excluded.mtime,
                        status       = 'failed',
                        processed_at = excluded.processed_at,
                        error_msg    = excluded.error_msg
                """, (path, mtime, now, error))

    def get_status(self, path: str) -> Optional[str]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM processed_files WHERE path = ?", (path,)
                ).fetchone()
        return row['status'] if row else None
