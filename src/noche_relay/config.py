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
    state_backend: str
    run_mode: str
    supabase_url: str | None
    supabase_secret_key: str | None
    edit_lookback: int
    poll_settle_seconds: int
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
        state_backend = values.get("STATE_BACKEND", "sqlite").strip().lower()
        if state_backend not in {"sqlite", "supabase"}:
            raise ValueError("STATE_BACKEND must be either sqlite or supabase")

        run_mode = values.get("RUN_MODE", "continuous").strip().lower()
        if run_mode not in {"continuous", "poll"}:
            raise ValueError("RUN_MODE must be either continuous or poll")

        supabase_url = values.get("SUPABASE_URL", "").strip() or None
        # Prefer Supabase's current sb_secret_ keys. Keep the legacy
        # service_role environment variable as a migration fallback.
        supabase_secret_key = (
            values.get("SUPABASE_SECRET_KEY", "").strip()
            or values.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
            or None
        )
        if state_backend == "supabase" and not (supabase_url and supabase_secret_key):
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SECRET_KEY are required "
                "when STATE_BACKEND=supabase"
            )

        try:
            edit_lookback = int(values.get("EDIT_LOOKBACK", "100"))
        except ValueError as exc:
            raise ValueError("EDIT_LOOKBACK must be an integer") from exc
        if edit_lookback < 0:
            raise ValueError("EDIT_LOOKBACK must be zero or greater")

        try:
            poll_settle_seconds = int(values.get("POLL_SETTLE_SECONDS", "30"))
        except ValueError as exc:
            raise ValueError("POLL_SETTLE_SECONDS must be an integer") from exc
        if poll_settle_seconds < 0:
            raise ValueError("POLL_SETTLE_SECONDS must be zero or greater")

        return cls(
            api_id=api_id,
            api_hash=values["API_HASH"].strip(),
            session=values["TELEGRAM_SESSION"].strip(),
            source_channel=parse_chat_ref(values["SOURCE_CHANNEL"]),
            target_channel=parse_chat_ref(values["TARGET_CHANNEL"]),
            state_db_path=state_path,
            state_backend=state_backend,
            run_mode=run_mode,
            supabase_url=supabase_url,
            supabase_secret_key=supabase_secret_key,
            edit_lookback=edit_lookback,
            poll_settle_seconds=poll_settle_seconds,
            log_level=values.get("LOG_LEVEL", "INFO").strip().upper(),
            silent=parse_bool(values.get("SILENT", "false")),
        )
