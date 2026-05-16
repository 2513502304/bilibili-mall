import os
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bilibili_mall.interactive_crawler import (
    CrawlerConfig,
    clear_crawl_outputs,
    detect_env_proxy,
    parse_cookie_header,
    read_crawl_state,
)
from bilibili_mall.crawler_options import (
    DiscountFilters,
    PieceFilters,
    SortType,
)


class CrawlerConfigTest(unittest.TestCase):
    def test_sort_type_does_not_keep_misspelled_price_aliases(self):
        self.assertNotIn("PIECE_DESC", SortType.__members__)
        self.assertNotIn("PIECE_ASC", SortType.__members__)

    def test_parse_cookie_header_splits_pairs_and_ignores_empty_parts(self):
        self.assertEqual(
            parse_cookie_header("SESSDATA=abc=123; bili_jct=token; ; DedeUserID=42"),
            {
                "SESSDATA": "abc=123",
                "bili_jct": "token",
                "DedeUserID": "42",
            },
        )

    def test_detect_env_proxy_prefers_https_then_http_then_all_proxy(self):
        with patch.dict(
            os.environ,
            {
                "HTTPS_PROXY": "http://127.0.0.1:7890",
                "HTTP_PROXY": "http://127.0.0.1:7891",
                "ALL_PROXY": "socks5://127.0.0.1:7892",
            },
            clear=True,
        ):
            self.assertEqual(detect_env_proxy(), "http://127.0.0.1:7890")

        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:7891"}, clear=True):
            self.assertEqual(detect_env_proxy(), "http://127.0.0.1:7891")

    def test_build_requests_expands_multiple_sort_types(self):
        config = CrawlerConfig(
            sort_types=(SortType.TIME_DESC, SortType.PRICE_ASC),
            price_filters=(PieceFilters.BELOW_TWENTY, PieceFilters.OVER_TWO_HUNDRED),
            discount_filters=(DiscountFilters.BELOW_THIRTY,),
            cookie_header="SESSDATA=abc",
        )

        requests = config.build_requests()

        self.assertEqual([request.sort_type for request in requests], [SortType.TIME_DESC, SortType.PRICE_ASC])
        self.assertEqual(requests[0].price_filters, ["0-2000", "20000-0"])
        self.assertEqual(requests[0].discount_filters, ["0-30"])
        self.assertEqual(requests[1].price_filters, ["0-2000", "20000-0"])

    def test_request_payload_uses_none_for_empty_discount_filters(self):
        config = CrawlerConfig(
            sort_types=(SortType.PRICE_DESC,),
            price_filters=(PieceFilters.TWENTY2THIRTY,),
            discount_filters=(),
            cookie_header="SESSDATA=abc",
        )

        payload = config.build_requests()[0].to_payload(next_id="cursor-1")

        self.assertEqual(
            payload,
            {
                "nextId": "cursor-1",
                "sortType": "PRICE_DESC",
                "priceFilters": ["2000-3000"],
                "discountFilters": None,
            },
        )

    def test_max_retries_defaults_to_ten_and_can_be_overridden(self):
        self.assertEqual(CrawlerConfig().max_retries, 10)
        self.assertEqual(CrawlerConfig(max_retries=3).max_retries, 3)

    def test_sleep_range_defaults_to_more_conservative_interval(self):
        self.assertEqual(CrawlerConfig().sleep_range, (1.25, 1.5))

    def test_config_state_round_trips_enum_names(self):
        config = CrawlerConfig(
            sort_types=("PRICE_DESC",),
            price_filters=("BELOW_TWENTY",),
            discount_filters=("OVER_SEVENTY",),
            cookie_header="SESSDATA=abc",
        )

        self.assertEqual(
            config.to_state(),
            {
                "sort_types": ["PRICE_DESC"],
                "price_filters": ["BELOW_TWENTY"],
                "discount_filters": ["OVER_SEVENTY"],
            },
        )

    def test_clear_crawl_outputs_can_keep_existing_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_path = data_dir / "bmall_all_data.jsonl"
            state_path = data_dir / "bmall_crawl_state.json"
            next_id_path = data_dir / "bmall_next_id.txt"
            data_path.write_text("{}\n", encoding="utf-8")
            state_path.write_text("{}", encoding="utf-8")
            next_id_path.write_text("cursor", encoding="utf-8")

            asyncio.run(clear_crawl_outputs(data_dir, include_data=False))

            self.assertTrue(data_path.exists())
            self.assertFalse(state_path.exists())
            self.assertFalse(next_id_path.exists())

    def test_clear_crawl_outputs_can_remove_existing_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_path = data_dir / "bmall_all_data.jsonl"
            data_path.write_text("{}\n", encoding="utf-8")

            asyncio.run(clear_crawl_outputs(data_dir, include_data=True))

            self.assertFalse(data_path.exists())

    def test_read_crawl_state_returns_empty_dict_for_missing_or_invalid_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            self.assertEqual(read_crawl_state(data_dir), {})
            (data_dir / "bmall_crawl_state.json").write_text("{", encoding="utf-8")
            self.assertEqual(read_crawl_state(data_dir), {})


if __name__ == "__main__":
    unittest.main()
