from pathlib import Path
from types import SimpleNamespace
import unittest

from noche_relay.app import _run_poll, group_messages
from noche_relay.config import Settings


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
            source_channel="@source",
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


if __name__ == "__main__":
    unittest.main()
