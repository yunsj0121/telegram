from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable, Protocol


@dataclass(frozen=True)
class MessageMapping:
    source_message_id: int
    target_message_id: int
    grouped_id: int | None = None
    source_edit_date: str | None = None


class StateStore(Protocol):
    def close(self) -> None: ...

    def get_cursor(self) -> int | None: ...

    def set_cursor(self, source_message_id: int) -> None: ...

    def get_target_id(self, source_message_id: int) -> int | None: ...

    def has_any(self, source_message_ids: Iterable[int]) -> bool: ...

    def save_many(self, mappings: Iterable[MessageMapping]) -> None: ...

    def list_recent(self, limit: int) -> list[MessageMapping]: ...

    def mark_edit_synced(self, source_message_id: int, edit_date: str) -> None: ...


class RelayState:
    """Persistent source-to-target message mapping used for deduplication and edits."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS message_map (
                source_message_id INTEGER PRIMARY KEY,
                target_message_id INTEGER NOT NULL,
                grouped_id INTEGER,
                source_edit_date TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {
            str(row[1]) for row in self._connection.execute("PRAGMA table_info(message_map)")
        }
        if "source_edit_date" not in columns:
            self._connection.execute(
                "ALTER TABLE message_map ADD COLUMN source_edit_date TEXT"
            )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS relay_cursor (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                last_source_message_id INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def get_cursor(self) -> int | None:
        row = self._connection.execute(
            "SELECT last_source_message_id FROM relay_cursor WHERE singleton = 1"
        ).fetchone()
        return None if row is None else int(row[0])

    def set_cursor(self, source_message_id: int) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO relay_cursor (singleton, last_source_message_id, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    last_source_message_id = excluded.last_source_message_id,
                    updated_at = excluded.updated_at
                """,
                (source_message_id, updated_at),
            )

    def get_target_id(self, source_message_id: int) -> int | None:
        row = self._connection.execute(
            "SELECT target_message_id FROM message_map WHERE source_message_id = ?",
            (source_message_id,),
        ).fetchone()
        return None if row is None else int(row[0])

    def has_any(self, source_message_ids: Iterable[int]) -> bool:
        ids = tuple(source_message_ids)
        if not ids:
            return False
        placeholders = ",".join("?" for _ in ids)
        row = self._connection.execute(
            f"SELECT 1 FROM message_map WHERE source_message_id IN ({placeholders}) LIMIT 1",
            ids,
        ).fetchone()
        return row is not None

    def save_many(self, mappings: Iterable[MessageMapping]) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                item.source_message_id,
                item.target_message_id,
                item.grouped_id,
                item.source_edit_date,
                created_at,
            )
            for item in mappings
        ]
        if not rows:
            return
        with self._connection:
            self._connection.executemany(
                """
                INSERT OR IGNORE INTO message_map
                    (source_message_id, target_message_id, grouped_id,
                     source_edit_date, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

    def list_recent(self, limit: int) -> list[MessageMapping]:
        if limit <= 0:
            return []
        rows = self._connection.execute(
            """
            SELECT source_message_id, target_message_id, grouped_id, source_edit_date
            FROM message_map
            ORDER BY source_message_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            MessageMapping(
                source_message_id=int(row[0]),
                target_message_id=int(row[1]),
                grouped_id=None if row[2] is None else int(row[2]),
                source_edit_date=None if row[3] is None else str(row[3]),
            )
            for row in rows
        ]

    def mark_edit_synced(self, source_message_id: int, edit_date: str) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE message_map
                SET source_edit_date = ?
                WHERE source_message_id = ?
                """,
                (edit_date, source_message_id),
            )
