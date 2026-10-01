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
            state.close()


if __name__ == "__main__":
    unittest.main()

