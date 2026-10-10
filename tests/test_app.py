import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from telethon.errors import MediaCaptionTooLongError, MessageNotModifiedError

from noche_relay.app import (
    _register_continuous_handlers,
    _run_poll,
    _sync_recent_edits,
    group_messages,
)
from noche_relay.config import Settings
from noche_relay.state import MessageMapping, RelayState


class GroupMessagesTests(unittest.TestCase):
    def test_groups_albums_and_preserves_order(self):
        messages = [
            SimpleNamespace(id=13, grouped_id=None),
            SimpleNamespace(id=11, grouped_id=900),
            SimpleNamespace(id=10, grouped_id=None),
            SimpleNamespace(id=12, grouped_id=900),
        ]

        groups = group_messages(messages)

        self.assertEqual(
            [[item.id for item in group] for group in groups],
            [[10], [11, 12], [13]],
        )


class PollRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_processes_new_messages_in_album_groups(self):
        messages = [
            SimpleNamespace(id=11, grouped_id=900, edit_date=None),
            SimpleNamespace(id=12, grouped_id=900, edit_date=None),
            SimpleNamespace(id=13, grouped_id=None, edit_date=None),
        ]

        class FakeClient:
            def __init__(self):
                self.forwarded_groups = []

            async def iter_messages(self, source, min_id, reverse):
                self.assertions = (source, min_id, reverse)
                for message in messages:
                    yield message

            async def forward_messages(self, target, source_messages, **kwargs):
                self.forwarded_groups.append([item.id for item in source_messages])
                return [
                    SimpleNamespace(id=1000 + item.id) for item in source_messages
                ]

        class FakeState:
            def __init__(self):
                self.cursor = 10
                self.mappings = {}

            def get_cursor(self):
                return self.cursor

            def set_cursor(self, value):
                self.cursor = value

            def get_target_id(self, value):
                return self.mappings.get(value)

            def save_many(self, values):
                for item in values:
                    self.mappings[item.source_message_id] = item.target_message_id

            def list_recent(self, limit):
                return []

        client = FakeClient()
        state = FakeState()
        settings = Settings(
            api_id=1,
            api_hash="hash",
            session="session",
            source_channels=("@source",),
            target_channel="@target",
            state_db_path=Path("state.sqlite3"),
            state_backend="sqlite",
            run_mode="poll",
            supabase_url=None,
            supabase_secret_key=None,
            edit_lookback=0,
            poll_settle_seconds=0,
            log_level="INFO",
            silent=False,
        )

        await _run_poll(client, "source", "target", state, settings)

        self.assertEqual(client.assertions, ("source", 10, True))
        self.assertEqual(client.forwarded_groups, [[11, 12], [13]])
        self.assertEqual(state.cursor, 13)
        self.assertEqual(state.mappings, {11: 1011, 12: 1012, 13: 1013})


class EditSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.state = RelayState(Path(":memory:"))
        self.addCleanup(self.state.close)
        self.edit_date = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
        self.messages = [
            SimpleNamespace(
                id=source_id,
                message="Same text",
                entities=[],
                edit_date=self.edit_date,
            )
            for source_id in (10, 11)
        ]
        self.state.save_many([MessageMapping(10, 110), MessageMapping(11, 111)])
        self.client = SimpleNamespace(
            get_messages=AsyncMock(return_value=self.messages),
            edit_message=AsyncMock(),
        )

    async def test_already_matching_edit_is_saved_and_later_edits_continue(self):
        self.client.edit_message.side_effect = [
            MessageNotModifiedError(request=None),
            None,
        ]

        await _sync_recent_edits(self.client, "source", "target", self.state, 100)

        self.assertEqual(self.client.edit_message.await_count, 2)
        self.assertEqual(
            [call.args[1] for call in self.client.edit_message.await_args_list],
            [110, 111],
        )
        self.assertTrue(all(
            mapping.source_edit_date == self.edit_date.isoformat()
            for mapping in self.state.list_recent(100)
        ))

        # A later polling run must not retry either synchronized edit.
        await _sync_recent_edits(self.client, "source", "target", self.state, 100)
        self.assertEqual(self.client.edit_message.await_count, 2)

    async def test_too_long_media_caption_does_not_block_later_edits(self):
        self.client.edit_message.side_effect = [
            MediaCaptionTooLongError(request=None),
            None,
        ]

        await _sync_recent_edits(self.client, "source", "target", self.state, 100)

        self.assertEqual(self.client.edit_message.await_count, 2)
        self.assertTrue(all(
            mapping.source_edit_date == self.edit_date.isoformat()
            for mapping in self.state.list_recent(100)
        ))

        # The known uneditable caption is recorded so it cannot block future runs.
        await _sync_recent_edits(self.client, "source", "target", self.state, 100)
        self.assertEqual(self.client.edit_message.await_count, 2)

    async def test_real_edit_failure_is_not_marked_as_synchronized(self):
        self.client.edit_message.side_effect = RuntimeError("permission denied")

        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            await _sync_recent_edits(self.client, "source", "target", self.state, 100)

        self.assertTrue(all(
            mapping.source_edit_date is None
            for mapping in self.state.list_recent(100)
        ))

    async def test_continuous_handler_saves_already_matching_edit(self):
        handlers = []

        def register(event):
            def decorator(handler):
                handlers.append(handler)
                return handler
            return decorator

        self.client.on = Mock(side_effect=register)
        self.client.edit_message.side_effect = MessageNotModifiedError(request=None)
        await _register_continuous_handlers(
            self.client, "source", "target", self.state,
            SimpleNamespace(silent=False), asyncio.Lock(),
        )
        on_message_edited = next(
            handler for handler in handlers
            if handler.__name__ == "on_message_edited"
        )

        with self.assertLogs("noche_relay", level="INFO") as logs:
            await on_message_edited(SimpleNamespace(message=self.messages[0]))

        mapping = next(
            item for item in self.state.list_recent(100)
            if item.source_message_id == 10
        )
        self.assertEqual(mapping.source_edit_date, self.edit_date.isoformat())
        self.assertFalse(any(record.levelname == "ERROR" for record in logs.records))


if __name__ == "__main__":
    unittest.main()
