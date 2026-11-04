"""Job history: every download Fetcher has started, kept after aria2 forgets it.

aria2 only remembers unfinished jobs across restarts, so this database is the
source of truth for the list, for favorites/hidden flags, and - importantly -
for which files on the share Fetcher is allowed to serve or delete. A file is
only ever touched if it is recorded here AND still matches the identity
(device, inode, size) recorded when the download finished.
"""

import os
import sqlite3
import threading
import time

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    gid          TEXT,             -- current aria2 gid (NULL once aria2 forgot it)
    url          TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'waiting',
    name         TEXT NOT NULL DEFAULT '',
    path         TEXT NOT NULL DEFAULT '',
    total        INTEGER NOT NULL DEFAULT 0,
    done         INTEGER NOT NULL DEFAULT 0,
    error        TEXT NOT NULL DEFAULT '',
    added_at     REAL NOT NULL,
    finished_at  REAL,
    favorite     INTEGER NOT NULL DEFAULT 0,
    hidden       INTEGER NOT NULL DEFAULT 0,
    speed_limit  INTEGER NOT NULL DEFAULT 0,
    file_dev     INTEGER,
    file_ino     INTEGER,
    file_size    INTEGER,
    file_mtime   INTEGER,          -- ns; with dev/ino/size proves it's still our file
    file_deleted INTEGER NOT NULL DEFAULT 0,
    sha256       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS jobs_gid ON jobs(gid);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

COLUMNS = ["id", "gid", "url", "category", "status", "name", "path", "total",
           "done", "error", "added_at", "finished_at", "favorite", "hidden",
           "speed_limit", "file_deleted", "sha256"]


class DB:
    def __init__(self, path: str | None = None):
        path = path or os.path.join(config.STATE_DIR, "fetcher.db")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            # Columns added after the first release.
            have = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
            for col, decl in [("file_mtime", "INTEGER")]:
                if col not in have:
                    self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {decl}")
        # Bumped on every write; the UI gets a full list only when it changes.
        self.version = 1

    def _exec(self, sql: str, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            if not sql.lstrip().upper().startswith("SELECT"):
                self.version += 1
            return cur

    # --- jobs -------------------------------------------------------------

    def add(self, url: str, category: str, gid: str, status: str) -> int:
        cur = self._exec(
            "INSERT INTO jobs (gid, url, category, status, added_at) VALUES (?,?,?,?,?)",
            (gid, url, category, status, time.time()))
        return cur.lastrowid

    def get(self, job_id: int) -> dict | None:
        row = self._exec("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def by_gid(self) -> dict[str, dict]:
        rows = self._exec("SELECT * FROM jobs WHERE gid IS NOT NULL").fetchall()
        return {r["gid"]: dict(r) for r in rows}

    def all(self) -> list[dict]:
        cols = ", ".join(COLUMNS)
        rows = self._exec(f"SELECT {cols} FROM jobs ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def update(self, job_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), job_id))

    def delete(self, job_id: int) -> None:
        self._exec("DELETE FROM jobs WHERE id=?", (job_id,))

    def categories(self) -> list[str]:
        rows = self._exec(
            "SELECT DISTINCT category FROM jobs WHERE category != '' ORDER BY category").fetchall()
        return [r[0] for r in rows]

    # --- settings -----------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._exec("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings (key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
