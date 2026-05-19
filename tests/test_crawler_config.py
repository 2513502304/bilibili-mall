import os
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import orjson

from bilibili_mall.interactive_crawler import (
    DATA_RETENTION_DAYS,
    RECORDED_AT_FIELD,
    BMallSpider,
    CrawlPage,
    CrawlRunContext,
    CrawlerConfig,
    clear_crawl_outputs,
    detect_env_proxy,
    error_backoff_seconds,
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

    def test_data_retention_defaults_to_market_listing_lifetime(self):
        self.assertEqual(CrawlerConfig().data_retention_days, DATA_RETENTION_DAYS)

    def test_data_retention_keeps_at_least_one_day(self):
        self.assertEqual(CrawlerConfig(data_retention_days=0).data_retention_days, 1)

    def test_error_backoff_exponentially_increases_and_caps_at_three_seconds(self):
        self.assertEqual(error_backoff_seconds(1), 0.3)
        self.assertEqual(error_backoff_seconds(2), 0.6)
        self.assertEqual(error_backoff_seconds(3), 1.2)
        self.assertEqual(error_backoff_seconds(4), 2.4)
        self.assertEqual(error_backoff_seconds(5), 3.0)
        self.assertEqual(error_backoff_seconds(10), 3.0)

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

    def test_prepare_run_migrates_legacy_rows_and_drops_expired_rows(self):
        async def run_case(data_dir: Path):
            config = CrawlerConfig(cookie_header="SESSDATA=abc", data_dir=data_dir)
            spider = BMallSpider(config)
            try:
                return await spider._prepare_run(reset=False, restart=False)
            finally:
                await spider.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            data_path = data_dir / "bmall_all_data.jsonl"
            now = int(time.time())
            expired_timestamp = now - (DATA_RETENTION_DAYS + 1) * 24 * 60 * 60
            recent_timestamp = now - 60
            data_path.write_text(
                "\n".join(
                    [
                        '{"c2cItemsId": "legacy"}',
                        f'{{"c2cItemsId": "expired", "{RECORDED_AT_FIELD}": {expired_timestamp}}}',
                        f'{{"c2cItemsId": "recent", "{RECORDED_AT_FIELD}": {recent_timestamp}}}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            context = asyncio.run(run_case(data_dir))
            rows = [
                orjson.loads(line)
                for line in data_path.read_bytes().splitlines()
            ]

            self.assertEqual(context.total_items, 2)
            self.assertEqual(context.dropped_expired_items, 1)
            self.assertEqual(context.migrated_legacy_items, 1)
            self.assertEqual({row["c2cItemsId"] for row in rows}, {"legacy", "recent"})
            self.assertTrue(all(RECORDED_AT_FIELD in row for row in rows))

    def test_store_page_items_adds_recorded_at_to_new_rows(self):
        async def run_case(data_dir: Path):
            config = CrawlerConfig(cookie_header="SESSDATA=abc", data_dir=data_dir)
            spider = BMallSpider(config)
            context = CrawlRunContext(
                requests=config.build_requests(),
                fingerprint=config.fingerprint(),
                request_index=0,
                next_id=None,
                total_items=0,
                seen_item_ids=set(),
            )
            try:
                await spider._store_page_items(
                    CrawlPage(items=[{"c2cItemsId": "new"}], next_id=None),
                    context,
                )
            finally:
                await spider.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            asyncio.run(run_case(data_dir))
            row = orjson.loads(
                (data_dir / "bmall_all_data.jsonl").read_bytes().splitlines()[0]
            )

            self.assertEqual(row["c2cItemsId"], "new")
            self.assertIsInstance(row[RECORDED_AT_FIELD], int)


if __name__ == "__main__":
    unittest.main()
