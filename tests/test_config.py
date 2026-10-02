import unittest

from noche_relay.config import Settings, parse_bool, parse_chat_ref, parse_chat_refs


class ConfigTests(unittest.TestCase):
    def test_parse_chat_ref(self):
        self.assertEqual(parse_chat_ref(" @aetherjapanresearch "), "@aetherjapanresearch")
        self.assertEqual(parse_chat_ref("-100123456789"), -100123456789)

    def test_parse_chat_refs(self):
        self.assertEqual(
            parse_chat_refs(" @first, -100123456789, @third "),
            ("@first", -100123456789, "@third"),
        )
        with self.assertRaises(ValueError):
            parse_chat_refs(" , ")

    def test_parse_bool(self):
        self.assertTrue(parse_bool("YES"))
        self.assertFalse(parse_bool("off"))
        with self.assertRaises(ValueError):
            parse_bool("sometimes")

    def test_settings_from_env(self):
        settings = Settings.from_env(
            {
                "API_ID": "123",
                "API_HASH": "hash",
                "TELEGRAM_SESSION": "session",
                "SOURCE_CHANNELS": "@source,@second_source",
                "TARGET_CHANNEL": "@target",
                "STATE_DB_PATH": "./state.sqlite3",
                "RUN_MODE": "poll",
                "SILENT": "true",
            }
        )
        self.assertEqual(settings.api_id, 123)
        self.assertEqual(settings.source_channels, ("@source", "@second_source"))
        self.assertEqual(settings.run_mode, "poll")
        self.assertEqual(settings.state_backend, "sqlite")
        self.assertEqual(settings.poll_settle_seconds, 30)
        self.assertTrue(settings.silent)

    def test_missing_required_values(self):
        with self.assertRaisesRegex(ValueError, "API_HASH"):
            Settings.from_env({"API_ID": "123"})

    def test_supabase_backend_requires_secrets(self):
        with self.assertRaisesRegex(ValueError, "SUPABASE_URL"):
            Settings.from_env(
                {
                    "API_ID": "123",
                    "API_HASH": "hash",
                    "TELEGRAM_SESSION": "session",
                    "SOURCE_CHANNEL": "@source",
                    "TARGET_CHANNEL": "@target",
                    "STATE_BACKEND": "supabase",
                }
            )

    def test_supabase_secret_key_is_preferred(self):
        settings = Settings.from_env(
            {
                "API_ID": "123",
                "API_HASH": "hash",
                "TELEGRAM_SESSION": "session",
                "SOURCE_CHANNEL": "@source",
                "TARGET_CHANNEL": "@target",
                "STATE_BACKEND": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "sb_secret_current",
                "SUPABASE_SERVICE_ROLE_KEY": "legacy-key",
            }
        )
        self.assertEqual(settings.supabase_secret_key, "sb_secret_current")

    def test_legacy_service_role_key_is_supported(self):
        settings = Settings.from_env(
            {
                "API_ID": "123",
                "API_HASH": "hash",
                "TELEGRAM_SESSION": "session",
                "SOURCE_CHANNEL": "@source",
                "TARGET_CHANNEL": "@target",
                "STATE_BACKEND": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "legacy-key",
            }
        )
        self.assertEqual(settings.supabase_secret_key, "legacy-key")

    def test_legacy_source_channel_name_is_supported(self):
        settings = Settings.from_env(
            {
                "API_ID": "123",
                "API_HASH": "hash",
                "TELEGRAM_SESSION": "session",
                "SOURCE_CHANNEL": "@legacy",
                "TARGET_CHANNEL": "@target",
            }
        )
        self.assertEqual(settings.source_channels, ("@legacy",))


if __name__ == "__main__":
    unittest.main()
