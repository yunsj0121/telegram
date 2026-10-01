from pathlib import Path
import tempfile
import unittest

from noche_relay.state import MessageMapping, RelayState


class RelayStateTests(unittest.TestCase):
    def test_save_lookup_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state = RelayState(Path(temp_dir) / "relay.sqlite3")
            state.save_many(
                [
                    MessageMapping(10, 110, 77),
                    MessageMapping(11, 111, 77),
                ]
            )

            self.assertEqual(state.get_target_id(10), 110)
            self.assertIsNone(state.get_target_id(99))
            self.assertTrue(state.has_any([9, 10]))
            self.assertFalse(state.has_any([98, 99]))

            state.save_many([MessageMapping(10, 999, 77)])
            self.assertEqual(state.get_target_id(10), 110)

            self.assertIsNone(state.get_cursor())
            state.set_cursor(11)
            self.assertEqual(state.get_cursor(), 11)
            state.set_cursor(12)
            self.assertEqual(state.get_cursor(), 12)

            recent = state.list_recent(1)
            self.assertEqual(recent[0].source_message_id, 11)
            state.mark_edit_synced(11, "2026-10-01T12:00:00+00:00")
            self.assertEqual(
                state.list_recent(1)[0].source_edit_date,
                "2026-10-01T12:00:00+00:00",
            )
            state.close()


if __name__ == "__main__":
    unittest.main()
