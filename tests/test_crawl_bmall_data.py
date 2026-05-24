import unittest
from unittest.mock import patch

from bilibili_mall.crawler_options import PieceFilters
from scripts.crawl_bmall_data import _bool_env, _price_filters_from_env


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

    def test_price_filters_default_to_all_ranges(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(_price_filters_from_env(), tuple(PieceFilters))

    def test_price_filters_can_select_multiple_ranges(self):
        with patch.dict(
            "os.environ",
            {
                "BMALL_PRICE_BELOW_TWENTY": "false",
                "BMALL_PRICE_TWENTY_TO_THIRTY": "false",
                "BMALL_PRICE_THIRTY_TO_FIFTY": "false",
                "BMALL_PRICE_FIFTY_TO_HUNDRED": "false",
                "BMALL_PRICE_HUNDRED_TO_TWO_HUNDRED": "true",
                "BMALL_PRICE_OVER_TWO_HUNDRED": "true",
            },
            clear=True,
        ):
            self.assertEqual(
                _price_filters_from_env(),
                (PieceFilters.HUNDRED2TWO_HUNDRED, PieceFilters.OVER_TWO_HUNDRED),
            )

    def test_price_filters_reject_empty_selection(self):
        with patch.dict(
            "os.environ",
            {
                "BMALL_PRICE_BELOW_TWENTY": "false",
                "BMALL_PRICE_TWENTY_TO_THIRTY": "false",
                "BMALL_PRICE_THIRTY_TO_FIFTY": "false",
                "BMALL_PRICE_FIFTY_TO_HUNDRED": "false",
                "BMALL_PRICE_HUNDRED_TO_TWO_HUNDRED": "false",
                "BMALL_PRICE_OVER_TWO_HUNDRED": "false",
            },
            clear=True,
        ):
            with self.assertRaises(SystemExit):
                _price_filters_from_env()


if __name__ == "__main__":
    unittest.main()
