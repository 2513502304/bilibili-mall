import unittest

from bilibili_mall.app_config import configured_value, slider_bounds


class MissingSecrets(Exception):
    pass


class AppConfigTest(unittest.TestCase):
    def test_configured_value_prefers_secret(self):
        self.assertEqual(
            configured_value(
                "BMALL_DATA_URL",
                env={"BMALL_DATA_URL": "https://env.example/data.jsonl"},
                secret_getter=lambda key: "https://secret.example/data.jsonl",
                missing_secret_errors=(MissingSecrets,),
            ),
            "https://secret.example/data.jsonl",
        )

    def test_configured_value_uses_env_when_secrets_are_missing(self):
        def missing_secret(_key: str) -> str:
            raise MissingSecrets("No secrets found")

        self.assertEqual(
            configured_value(
                "BMALL_DATA_URL",
                env={"BMALL_DATA_URL": "https://env.example/data.jsonl"},
                secret_getter=missing_secret,
                missing_secret_errors=(MissingSecrets,),
            ),
            "https://env.example/data.jsonl",
        )

    def test_configured_value_returns_empty_string_without_secret_or_env(self):
        def missing_secret(_key: str) -> str:
            raise MissingSecrets("No secrets found")

        self.assertEqual(
            configured_value(
                "BMALL_DATA_URL",
                env={},
                secret_getter=missing_secret,
                missing_secret_errors=(MissingSecrets,),
            ),
            "",
        )

    def test_slider_bounds_returns_none_when_min_and_max_are_equal(self):
        self.assertIsNone(slider_bounds(10000, 10000))

    def test_slider_bounds_returns_range_when_min_is_less_than_max(self):
        self.assertEqual(slider_bounds(10, 20), (10, 20))


if __name__ == "__main__":
    unittest.main()
