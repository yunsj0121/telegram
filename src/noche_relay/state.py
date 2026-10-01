from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable


@dataclass(frozen=True)
class MessageMapping:
    source_message_id: int
    target_message_id: int
    grouped_id: int | None = None


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
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

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
            (item.source_message_id, item.target_message_id, item.grouped_id, created_at)
            for item in mappings
        ]
        if not rows:
            return
        with self._connection:
            self._connection.executemany(
                """
                INSERT OR IGNORE INTO message_map
                    (source_message_id, target_message_id, grouped_id, created_at)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

