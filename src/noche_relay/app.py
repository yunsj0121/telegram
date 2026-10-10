from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from pathlib import Path
from typing import Iterable, Sequence

from telethon import TelegramClient, events
from telethon.errors import (
    ChatForwardsRestrictedError,
    FloodWaitError,
    MediaCaptionTooLongError,
    MessageNotModifiedError,
    MessageTooLongError,
)
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

from .config import Settings
from .state import MessageMapping, RelayState, StateStore
from .supabase_state import SupabaseRelayState


LOGGER = logging.getLogger("noche_relay")


def _as_messages(
    result: Message | Sequence[Message] | None,
) -> list[Message]:
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return [item for item in result if item is not None]
    return [result]


def group_messages(messages: Iterable[Message]) -> list[list[Message]]:
    """Keep albums together while preserving chronological post order."""
    groups: OrderedDict[tuple[str, int], list[Message]] = OrderedDict()
    for message in sorted(messages, key=lambda item: item.id):
        key = (
            ("album", int(message.grouped_id))
            if message.grouped_id is not None
            else ("message", int(message.id))
        )
        groups.setdefault(key, []).append(message)
    return list(groups.values())


def _edit_date(message: Message) -> str | None:
    value: datetime | None = message.edit_date
    return None if value is None else value.isoformat()


async def _with_flood_wait(operation):
    while True:
        try:
            return await operation()
        except FloodWaitError as exc:
            LOGGER.warning("Telegram rate limit: waiting %s seconds", exc.seconds)
            await asyncio.sleep(exc.seconds + 1)


async def _with_edit_flood_wait(operation) -> None:
    """Treat an already matching target as a successfully synchronized edit."""
    try:
        await _with_flood_wait(operation)
    except MessageNotModifiedError:
        LOGGER.info("Target message already matches; marking edit as synchronized")
    except (MediaCaptionTooLongError, MessageTooLongError):
        LOGGER.warning(
            "Skipping edit because Telegram rejected the text or caption as too long; "
            "continuing with the next message"
        )


def _state_path_for_source(settings: Settings, source_channel: int | str) -> Path:
    """Keep legacy SQLite paths for one source and isolate multi-source state."""
    if len(settings.source_channels) == 1:
        return settings.state_db_path
    digest = hashlib.sha256(str(source_channel).encode("utf-8")).hexdigest()[:12]
    return settings.state_db_path.with_name(
        f"{settings.state_db_path.stem}-{digest}{settings.state_db_path.suffix}"
    )


def _build_state(settings: Settings, source_channel: int | str) -> StateStore:
    if settings.state_backend == "supabase":
        assert settings.supabase_url is not None
        assert settings.supabase_secret_key is not None
        return SupabaseRelayState(
            settings.supabase_url,
            settings.supabase_secret_key,
            source_channel,
            settings.target_channel,
        )
    return RelayState(_state_path_for_source(settings, source_channel))


async def _relay_messages(
    client: TelegramClient,
    source,
    target,
    state: StateStore,
    messages: Iterable[Message],
    *,
    silent: bool,
) -> None:
    source_messages = sorted(messages, key=lambda item: item.id)
    source_ids = [item.id for item in source_messages]
    if not source_ids:
        return

    mapped = [state.get_target_id(item) for item in source_ids]
    if all(item is not None for item in mapped):
        LOGGER.info("Skipping already relayed message(s): %s", source_ids)
        return
    if any(item is not None for item in mapped):
        raise RuntimeError(
            f"Partial relay state found for message group {source_ids}; "
            "manual review is required to avoid a duplicate album"
        )

    async def forward():
        return await client.forward_messages(
            target,
            source_messages,
            from_peer=source,
            drop_author=True,
            silent=silent,
        )

    try:
        forwarded = _as_messages(await _with_flood_wait(forward))
    except ChatForwardsRestrictedError:
        LOGGER.exception("Source channel content protection blocks message(s): %s", source_ids)
        raise

    if len(forwarded) != len(source_messages):
        raise RuntimeError(
            "Telegram returned "
            f"{len(forwarded)} target message(s) for {len(source_messages)} "
            "source message(s); state was not saved"
        )

    state.save_many(
        MessageMapping(
            source_message_id=source_message.id,
            target_message_id=target_message.id,
            grouped_id=source_message.grouped_id,
            source_edit_date=_edit_date(source_message),
        )
        for source_message, target_message in zip(
            source_messages, forwarded, strict=True
        )
    )
    LOGGER.info("Relayed %s -> %s", source_ids, [item.id for item in forwarded])


async def _sync_recent_edits(
    client: TelegramClient,
    source,
    target,
    state: StateStore,
    limit: int,
) -> None:
    mappings = state.list_recent(limit)
    if not mappings:
        return

    by_source_id = {item.source_message_id: item for item in mappings}
    fetched = _as_messages(
        await client.get_messages(source, ids=list(by_source_id))
    )
    for message in fetched:
        mapping = by_source_id.get(message.id)
        if mapping is None:
            continue
        current_edit_date = _edit_date(message)
        if current_edit_date is None or current_edit_date == mapping.source_edit_date:
            continue
        if message.message is None:
            LOGGER.info("Ignoring media-only edit for source message %s", message.id)
            state.mark_edit_synced(message.id, current_edit_date)
            continue

        async def edit():
            return await client.edit_message(
                target,
                mapping.target_message_id,
                message.message,
                formatting_entities=message.entities,
                link_preview=not bool(getattr(message, "no_webpage", False)),
            )

        await _with_edit_flood_wait(edit)
        state.mark_edit_synced(message.id, current_edit_date)
        LOGGER.info(
            "Synced target message %s from source %s",
            mapping.target_message_id,
            message.id,
        )


async def _run_poll(
    client: TelegramClient,
    source,
    target,
    state: StateStore,
    settings: Settings,
) -> None:
    cursor = state.get_cursor()
    if cursor is None:
        latest = _as_messages(await client.get_messages(source, limit=1))
        initial_cursor = latest[0].id if latest else 0
        state.set_cursor(initial_cursor)
        LOGGER.info(
            "Initialized polling cursor at source message %s; historical posts were not copied",
            initial_cursor,
        )
        return

    fetched_messages = [
        message
        async for message in client.iter_messages(
            source,
            min_id=cursor,
            reverse=True,
        )
    ]
    settle_before = datetime.now(timezone.utc) - timedelta(
        seconds=settings.poll_settle_seconds
    )
    new_messages = [
        message
        for message in fetched_messages
        if getattr(message, "date", None) is None or message.date <= settle_before
    ]
    for group in group_messages(new_messages):
        await _relay_messages(
            client,
            source,
            target,
            state,
            group,
            silent=settings.silent,
        )
        state.set_cursor(max(item.id for item in group))

    if new_messages:
        LOGGER.info("Polling run processed %s new message(s)", len(new_messages))
    else:
        LOGGER.info("Polling run found no new messages after %s", cursor)

    unsettled_count = len(fetched_messages) - len(new_messages)
    if unsettled_count:
        LOGGER.info(
            "Deferred %s very recent message(s) until the next run so albums can settle",
            unsettled_count,
        )

    await _sync_recent_edits(
        client,
        source,
        target,
        state,
        settings.edit_lookback,
    )


async def _run_continuous(
    client: TelegramClient,
    source,
    target,
    state: StateStore,
    settings: Settings,
) -> None:
    relay_lock = asyncio.Lock()

    await _register_continuous_handlers(
        client,
        source,
        target,
        state,
        settings,
        relay_lock,
    )
    await client.run_until_disconnected()


async def _register_continuous_handlers(
    client: TelegramClient,
    source,
    target,
    state: StateStore,
    settings: Settings,
    relay_lock: asyncio.Lock,
) -> None:

    async def relay(messages: Iterable[Message]) -> None:
        async with relay_lock:
            await _relay_messages(
                client,
                source,
                target,
                state,
                messages,
                silent=settings.silent,
            )

    @client.on(events.Album(chats=source))
    async def on_album(event: events.Album.Event) -> None:
        await relay(event.messages)

    @client.on(events.NewMessage(chats=source))
    async def on_new_message(event: events.NewMessage.Event) -> None:
        if event.message.grouped_id is not None:
            return
        await relay([event.message])

    @client.on(events.MessageEdited(chats=source))
    async def on_message_edited(event: events.MessageEdited.Event) -> None:
        target_message_id = state.get_target_id(event.message.id)
        if target_message_id is None:
            LOGGER.debug("No target mapping for edited source message %s", event.message.id)
            return
        if event.message.message is None:
            LOGGER.info("Ignoring media-only edit for source message %s", event.message.id)
            return

        async def edit():
            return await client.edit_message(
                target,
                target_message_id,
                event.message.message,
                formatting_entities=event.message.entities,
                link_preview=not bool(getattr(event.message, "no_webpage", False)),
            )

        try:
            await _with_edit_flood_wait(edit)
            if event.message.edit_date is not None:
                state.mark_edit_synced(
                    event.message.id, event.message.edit_date.isoformat()
                )
            LOGGER.info(
                "Synced target message %s from source %s",
                target_message_id,
                event.message.id,
            )
        except Exception:
            LOGGER.exception("Could not sync edit for source message %s", event.message.id)

async def run(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = TelegramClient(StringSession(settings.session), settings.api_id, settings.api_hash)
    states: list[StateStore] = []

    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(
                "TELEGRAM_SESSION is not authorized; generate a new string session"
            )

        target = await client.get_entity(settings.target_channel)
        sources = [
            await client.get_entity(source_channel)
            for source_channel in settings.source_channels
        ]
        account = await client.get_me()

        LOGGER.info(
            "Relay ready: mode=%s account=%s sources=%s target=%s",
            settings.run_mode,
            getattr(account, "username", None) or account.id,
            [getattr(source, "username", None) or source.id for source in sources],
            getattr(target, "username", None) or target.id,
        )

        if settings.run_mode == "poll":
            for source_ref, source in zip(settings.source_channels, sources, strict=True):
                state = _build_state(settings, source_ref)
                states.append(state)
                await _run_poll(client, source, target, state, settings)
        else:
            relay_lock = asyncio.Lock()
            for source_ref, source in zip(settings.source_channels, sources, strict=True):
                state = _build_state(settings, source_ref)
                states.append(state)
                await _register_continuous_handlers(
                    client,
                    source,
                    target,
                    state,
                    settings,
                    relay_lock,
                )
            await client.run_until_disconnected()
    finally:
        for state in states:
            state.close()
        await client.disconnect()


def main() -> None:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    asyncio.run(run(settings))
