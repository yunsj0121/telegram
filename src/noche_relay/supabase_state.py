from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import time
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .state import MessageMapping

LOGGER = logging.getLogger(__name__)
_CLOCK_SKEW_RETRY_DELAYS = (2.0, 4.0)


class SupabaseRelayState:
    """PostgREST-backed state for short-lived scheduled relay runs."""

    def __init__(
        self,
        url: str,
        secret_key: str,
        source_channel: int | str,
        target_channel: int | str,
        opener: Callable = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._base_url = f"{url.rstrip('/')}/rest/v1"
        self._key = secret_key
        self._source_channel = str(source_channel)
        self._target_channel = str(target_channel)
        self._opener = opener
        self._sleeper = sleeper

    def close(self) -> None:
        return None

    def _request(
        self,
        method: str,
        table: str,
        *,
        params: dict[str, str] | None = None,
        payload=None,
        prefer: str | None = None,
    ):
        query = f"?{urlencode(params)}" if params else ""
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "apikey": self._key,
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        for attempt in range(len(_CLOCK_SKEW_RETRY_DELAYS) + 1):
            request = Request(
                f"{self._base_url}/{table}{query}",
                data=data,
                headers=headers,
                method=method,
            )
            try:
                with self._opener(request, timeout=20) as response:
                    body = response.read()
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                is_clock_skew_error = False
                if exc.code == 401:
                    try:
                        error = json.loads(detail)
                        is_clock_skew_error = (
                            error.get("code") == "PGRST303"
                            and error.get("message") == "JWT issued at future"
                        )
                    except (json.JSONDecodeError, AttributeError):
                        pass

                if is_clock_skew_error and attempt < len(_CLOCK_SKEW_RETRY_DELAYS):
                    delay = _CLOCK_SKEW_RETRY_DELAYS[attempt]
                    LOGGER.warning(
                        "Supabase clock-skew response; retrying in %.0f seconds",
                        delay,
                    )
                    self._sleeper(delay)
                    continue

                raise RuntimeError(
                    f"Supabase request failed ({exc.code}): {detail}"
                ) from exc
            except URLError as exc:
                raise RuntimeError(f"Supabase request failed: {exc.reason}") from exc
        return None if not body else json.loads(body.decode("utf-8"))

    def _scope(self) -> dict[str, str]:
        return {
            "source_channel": f"eq.{self._source_channel}",
            "target_channel": f"eq.{self._target_channel}",
        }

    def get_cursor(self) -> int | None:
        rows = self._request(
            "GET",
            "telegram_relay_cursors",
            params={
                **self._scope(),
                "select": "last_source_message_id",
                "limit": "1",
            },
        )
        return None if not rows else int(rows[0]["last_source_message_id"])

    def set_cursor(self, source_message_id: int) -> None:
        self._request(
            "POST",
            "telegram_relay_cursors",
            params={"on_conflict": "source_channel,target_channel"},
            payload={
                "source_channel": self._source_channel,
                "target_channel": self._target_channel,
                "last_source_message_id": source_message_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def get_target_id(self, source_message_id: int) -> int | None:
        rows = self._request(
            "GET",
            "telegram_relay_message_map",
            params={
                **self._scope(),
                "source_message_id": f"eq.{source_message_id}",
                "select": "target_message_id",
                "limit": "1",
            },
        )
        return None if not rows else int(rows[0]["target_message_id"])

    def has_any(self, source_message_ids: Iterable[int]) -> bool:
        ids = tuple(int(item) for item in source_message_ids)
        if not ids:
            return False
        rows = self._request(
            "GET",
            "telegram_relay_message_map",
            params={
                **self._scope(),
                "source_message_id": f"in.({','.join(str(item) for item in ids)})",
                "select": "source_message_id",
                "limit": "1",
            },
        )
        return bool(rows)

    def save_many(self, mappings: Iterable[MessageMapping]) -> None:
        created_at = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "source_channel": self._source_channel,
                "target_channel": self._target_channel,
                "source_message_id": item.source_message_id,
                "target_message_id": item.target_message_id,
                "grouped_id": item.grouped_id,
                "source_edit_date": item.source_edit_date,
                "created_at": created_at,
            }
            for item in mappings
        ]
        if not rows:
            return
        self._request(
            "POST",
            "telegram_relay_message_map",
            params={
                "on_conflict": "source_channel,target_channel,source_message_id"
            },
            payload=rows,
            prefer="resolution=ignore-duplicates,return=minimal",
        )

    def list_recent(self, limit: int) -> list[MessageMapping]:
        if limit <= 0:
            return []
        rows = self._request(
            "GET",
            "telegram_relay_message_map",
            params={
                **self._scope(),
                "select": (
                    "source_message_id,target_message_id,grouped_id,source_edit_date"
                ),
                "order": "source_message_id.desc",
                "limit": str(limit),
            },
        )
        return [
            MessageMapping(
                source_message_id=int(row["source_message_id"]),
                target_message_id=int(row["target_message_id"]),
                grouped_id=(
                    None if row.get("grouped_id") is None else int(row["grouped_id"])
                ),
                source_edit_date=row.get("source_edit_date"),
            )
            for row in rows
        ]

    def mark_edit_synced(self, source_message_id: int, edit_date: str) -> None:
        self._request(
            "PATCH",
            "telegram_relay_message_map",
            params={
                **self._scope(),
                "source_message_id": f"eq.{source_message_id}",
            },
            payload={"source_edit_date": edit_date},
            prefer="return=minimal",
        )
