from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import InstagramEvent


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS target_state (
    username TEXT PRIMARY KEY,
    user_id TEXT,
    next_run_at REAL NOT NULL DEFAULT 0,
    last_checked_at TEXT
);

CREATE TABLE IF NOT EXISTS baselines (
    username TEXT NOT NULL,
    group_name TEXT NOT NULL,
    initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (username, group_name)
);

CREATE TABLE IF NOT EXISTS items (
    event_key TEXT PRIMARY KEY,
    instagram_id TEXT NOT NULL,
    username TEXT NOT NULL,
    content_type TEXT NOT NULL,
    group_name TEXT NOT NULL,
    caption TEXT,
    link TEXT NOT NULL,
    created_at TEXT,
    sort_timestamp REAL NOT NULL DEFAULT 0,
    preview_url TEXT,
    delivery_status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_delivery
    ON items (delivery_status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_items_username_created
    ON items (username, sort_timestamp DESC);
"""


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def ensure_target(self, username: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO target_state (username, next_run_at) VALUES (?, 0)",
            (username,),
        )
        self.connection.commit()

    def due_targets(self, now: float) -> list[str]:
        rows = self.connection.execute(
            "SELECT username FROM target_state WHERE next_run_at <= ? ORDER BY next_run_at, username",
            (now,),
        ).fetchall()
        return [str(row["username"]) for row in rows]

    def next_target_time(self) -> float | None:
        row = self.connection.execute(
            "SELECT MIN(next_run_at) AS next_run_at FROM target_state"
        ).fetchone()
        return (
            float(row["next_run_at"])
            if row and row["next_run_at"] is not None
            else None
        )

    def schedule_target(self, username: str, next_run_at: float) -> None:
        self.connection.execute(
            """UPDATE target_state
             SET next_run_at = ?, last_checked_at = CURRENT_TIMESTAMP
             WHERE username = ?""",
            (next_run_at, username),
        )
        self.connection.commit()

    def get_user_id(self, username: str) -> str | None:
        row = self.connection.execute(
            "SELECT user_id FROM target_state WHERE username = ?",
            (username,),
        ).fetchone()
        return str(row["user_id"]) if row and row["user_id"] else None

    def set_user_id(self, username: str, user_id: str) -> None:
        self.connection.execute(
            "UPDATE target_state SET user_id = ? WHERE username = ?",
            (user_id, username),
        )
        self.connection.commit()

    def add_group(
        self,
        username: str,
        group_name: str,
        events: list[InstagramEvent],
        send_existing: bool,
    ) -> tuple[int, int]:
        baseline = self.connection.execute(
            "SELECT 1 FROM baselines WHERE username = ? AND group_name = ?",
            (username, group_name),
        ).fetchone()
        first_run = baseline is None
        status = "pending" if send_existing or not first_run else "seeded"
        inserted = 0
        seeded = 0
        with self.connection:
            for event in events:
                result = self.connection.execute(
                    """INSERT OR IGNORE INTO items (
                       event_key, instagram_id, username, content_type, group_name,
                       caption, link, created_at, sort_timestamp, preview_url,
                       delivery_status, next_attempt_at
                     ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (
                        event.event_key,
                        event.instagram_id,
                        event.username,
                        event.content_type,
                        event.group_name,
                        event.caption,
                        event.link,
                        event.created_at,
                        event.sort_timestamp,
                        event.preview_url,
                        status,
                    ),
                )
                if result.rowcount:
                    inserted += 1
                    if status == "seeded":
                        seeded += 1
                else:
                    self.connection.execute(
                        """UPDATE items
                           SET caption = ?, link = ?, created_at = ?,
                               sort_timestamp = ?, preview_url = ?
                           WHERE event_key = ?
                             AND delivery_status IN ('pending', 'send_failed')""",
                        (
                            event.caption,
                            event.link,
                            event.created_at,
                            event.sort_timestamp,
                            event.preview_url,
                            event.event_key,
                        ),
                    )
            if first_run:
                self.connection.execute(
                    "INSERT INTO baselines (username, group_name) VALUES (?, ?)",
                    (username, group_name),
                )
        return inserted - seeded, seeded

    def due_items(self, now: float, limit: int = 20) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT * FROM items
             WHERE delivery_status IN ('pending', 'send_failed')
               AND next_attempt_at <= ?
             ORDER BY sort_timestamp, discovered_at
             LIMIT ?""",
            (now, limit),
        ).fetchall()

    def mark_delivered(self, event_key: str) -> None:
        self.connection.execute(
            """UPDATE items
             SET delivery_status = 'sent', delivered_at = CURRENT_TIMESTAMP,
                 last_error = NULL
             WHERE event_key = ?""",
            (event_key,),
        )
        self.connection.commit()

    def mark_failed(self, event_key: str, error: str, retry_at: float) -> None:
        self.connection.execute(
            """UPDATE items
             SET delivery_status = 'send_failed', attempts = attempts + 1,
                 next_attempt_at = ?, last_error = ?
             WHERE event_key = ?""",
            (retry_at, error[:1000], event_key),
        )
        self.connection.commit()

    def pending_count(self) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS total FROM items WHERE delivery_status IN ('pending', 'send_failed')"
        ).fetchone()
        return int(row["total"] if row else 0)
