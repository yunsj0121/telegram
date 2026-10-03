import json
import unittest
from io import BytesIO
from urllib.error import HTTPError

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
        result = self.payloads.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)


def http_error(code, payload):
    return HTTPError(
        "https://project.supabase.co/rest/v1/telegram_relay_cursors",
        code,
        "request failed",
        {},
        BytesIO(json.dumps(payload).encode("utf-8")),
    )


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
        self.assertEqual(cursor_request.headers["Apikey"], "service-key")
        self.assertNotIn("Authorization", cursor_request.headers)
        self.assertEqual(json.loads(cursor_request.data)["last_source_message_id"], 43)

        mapping_request = opener.requests[2][0]
        self.assertEqual(mapping_request.method, "POST")
        self.assertIn("telegram_relay_message_map", mapping_request.full_url)
        self.assertEqual(json.loads(mapping_request.data)[0]["source_message_id"], 43)

    def test_retries_transient_clock_skew_error(self):
        opener = FakeOpener(
            http_error(
                401,
                {"code": "PGRST303", "message": "JWT issued at future"},
            ),
            b"[]",
        )
        delays = []
        state = SupabaseRelayState(
            "https://project.supabase.co",
            "service-key",
            "@source",
            "@target",
            opener=opener,
            sleeper=delays.append,
        )

        self.assertIsNone(state.get_cursor())
        self.assertEqual(delays, [2.0])
        self.assertEqual(len(opener.requests), 2)

    def test_does_not_retry_other_unauthorized_errors(self):
        opener = FakeOpener(
            http_error(401, {"code": "PGRST301", "message": "Invalid JWT"})
        )
        delays = []
        state = SupabaseRelayState(
            "https://project.supabase.co",
            "service-key",
            "@source",
            "@target",
            opener=opener,
            sleeper=delays.append,
        )

        with self.assertRaisesRegex(RuntimeError, "Invalid JWT"):
            state.get_cursor()

        self.assertEqual(delays, [])
        self.assertEqual(len(opener.requests), 1)
