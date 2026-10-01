from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping


def parse_chat_ref(value: str) -> int | str:
    """Return numeric Telegram IDs as ints and usernames unchanged."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("channel reference cannot be empty")
    try:
        return int(cleaned)
    except ValueError:
        return cleaned


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session: str
    source_channel: int | str
    target_channel: int | str
    state_db_path: Path
    log_level: str
    silent: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if env is None else env

        required = ("API_ID", "API_HASH", "TELEGRAM_SESSION", "SOURCE_CHANNEL", "TARGET_CHANNEL")
        missing = [key for key in required if not values.get(key, "").strip()]
        if missing:
            raise ValueError(f"missing required environment variables: {', '.join(missing)}")

        try:
            api_id = int(values["API_ID"])
        except ValueError as exc:
            raise ValueError("API_ID must be an integer") from exc

        state_path = Path(values.get("STATE_DB_PATH", "./data/relay.sqlite3")).expanduser()
        return cls(
            api_id=api_id,
            api_hash=values["API_HASH"].strip(),
            session=values["TELEGRAM_SESSION"].strip(),
            source_channel=parse_chat_ref(values["SOURCE_CHANNEL"]),
            target_channel=parse_chat_ref(values["TARGET_CHANNEL"]),
            state_db_path=state_path,
            log_level=values.get("LOG_LEVEL", "INFO").strip().upper(),
            silent=parse_bool(values.get("SILENT", "false")),
        )

