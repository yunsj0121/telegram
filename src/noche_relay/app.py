from __future__ import annotations

import asyncio
import logging
from typing import Iterable, Sequence

from telethon import TelegramClient, events
from telethon.errors import ChatForwardsRestrictedError, FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

from .config import Settings
from .state import MessageMapping, RelayState


LOGGER = logging.getLogger("noche_relay")


def _as_messages(result: Message | Sequence[Message]) -> list[Message]:
    if isinstance(result, (list, tuple)):
        return list(result)
    return [result]


async def _with_flood_wait(operation):
    while True:
        try:
            return await operation()
        except FloodWaitError as exc:
            LOGGER.warning("Telegram rate limit: waiting %s seconds", exc.seconds)
            await asyncio.sleep(exc.seconds + 1)


async def run(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    state = RelayState(settings.state_db_path)
    client = TelegramClient(StringSession(settings.session), settings.api_id, settings.api_hash)
    relay_lock = asyncio.Lock()

    await client.connect()
    if not await client.is_user_authorized():
        state.close()
        raise RuntimeError("TELEGRAM_SESSION is not authorized; generate a new string session")

    source = await client.get_entity(settings.source_channel)
    target = await client.get_entity(settings.target_channel)
    account = await client.get_me()

    LOGGER.info(
        "Relay ready: account=%s source=%s target=%s",
        getattr(account, "username", None) or account.id,
        getattr(source, "username", None) or source.id,
        getattr(target, "username", None) or target.id,
    )

    async def relay(messages: Iterable[Message]) -> None:
        source_messages = sorted(messages, key=lambda item: item.id)
        source_ids = [item.id for item in source_messages]
        if not source_ids:
            return

        async with relay_lock:
            if state.has_any(source_ids):
                LOGGER.info("Skipping already relayed message(s): %s", source_ids)
                return

            async def forward():
                return await client.forward_messages(
                    target,
                    source_messages,
                    from_peer=source,
                    drop_author=True,
                    silent=settings.silent,
                )

            try:
                forwarded = _as_messages(await _with_flood_wait(forward))
            except ChatForwardsRestrictedError:
                LOGGER.exception("Source channel content protection blocks message(s): %s", source_ids)
                return

            if len(forwarded) != len(source_messages):
                LOGGER.error(
                    "Telegram returned %s target message(s) for %s source message(s); state not saved",
                    len(forwarded),
                    len(source_messages),
                )
                return

            state.save_many(
                MessageMapping(
                    source_message_id=source_message.id,
                    target_message_id=target_message.id,
                    grouped_id=source_message.grouped_id,
                )
                for source_message, target_message in zip(source_messages, forwarded, strict=True)
            )
            LOGGER.info("Relayed %s -> %s", source_ids, [item.id for item in forwarded])

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
            await _with_flood_wait(edit)
            LOGGER.info("Updated target message %s from source %s", target_message_id, event.message.id)
        except Exception:
            LOGGER.exception("Could not sync edit for source message %s", event.message.id)

    try:
        await client.run_until_disconnected()
    finally:
        state.close()
        await client.disconnect()


def main() -> None:
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc
    asyncio.run(run(settings))

