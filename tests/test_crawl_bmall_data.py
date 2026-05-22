import unittest
from unittest.mock import patch

from scripts.crawl_bmall_data import _bool_env


class CrawlBMallDataScriptTest(unittest.TestCase):
    def test_bool_env_defaults_when_missing_or_blank(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(_bool_env("RESET_DATA", True))
            self.assertFalse(_bool_env("RESET_DATA", False))

        with patch.dict("os.environ", {"RESET_DATA": "  "}, clear=True):
            self.assertTrue(_bool_env("RESET_DATA", True))

    def test_bool_env_accepts_common_truthy_values(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            with patch.dict("os.environ", {"RESET_DATA": value}, clear=True):
                self.assertTrue(_bool_env("RESET_DATA", False))

    def test_bool_env_treats_other_values_as_false(self):
        for value in ("0", "false", "no", "off"):
            with patch.dict("os.environ", {"RESET_DATA": value}, clear=True):
                self.assertFalse(_bool_env("RESET_DATA", True))


if __name__ == "__main__":
    unittest.main()
