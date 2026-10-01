import json
import unittest

from noche_relay.state import MessageMapping
from noche_relay.supabase_state import SupabaseRelayState


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class FakeOpener:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.payloads.pop(0))


class SupabaseRelayStateTests(unittest.TestCase):
    def test_reads_cursor_and_writes_mappings(self):
        opener = FakeOpener(b'[{"last_source_message_id":42}]', b"", b"")
        state = SupabaseRelayState(
            "https://project.supabase.co",
            "service-key",
            "@source",
            "@target",
            opener=opener,
        )

        self.assertEqual(state.get_cursor(), 42)
        state.set_cursor(43)
        state.save_many([MessageMapping(43, 143, 999)])

        cursor_request = opener.requests[1][0]
        self.assertEqual(cursor_request.method, "POST")
        self.assertIn("telegram_relay_cursors", cursor_request.full_url)
        self.assertEqual(json.loads(cursor_request.data)["last_source_message_id"], 43)

        mapping_request = opener.requests[2][0]
        self.assertEqual(mapping_request.method, "POST")
        self.assertIn("telegram_relay_message_map", mapping_request.full_url)
        self.assertEqual(json.loads(mapping_request.data)[0]["source_message_id"], 43)
