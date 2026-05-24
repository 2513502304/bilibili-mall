from __future__ import annotations

import asyncio
import os
from pathlib import Path

from bilibili_mall.interactive_crawler import (
    DATA_RETENTION_DAYS,
    BMallSpider,
    CrawlerConfig,
)
from bilibili_mall.crawler_options import (
    ENV_PROXY_KEYS,
    PRICE_FILTER_LABELS,
    PieceFilters,
)
from bilibili_mall.utils import logger


PRICE_FILTER_ENV = (
    ("BMALL_PRICE_BELOW_TWENTY", PieceFilters.BELOW_TWENTY),
    ("BMALL_PRICE_TWENTY_TO_THIRTY", PieceFilters.TWENTY2THIRTY),
    ("BMALL_PRICE_THIRTY_TO_FIFTY", PieceFilters.THIRTY2FIFTY),
    ("BMALL_PRICE_FIFTY_TO_HUNDRED", PieceFilters.FIFTY2HUNDRED),
    ("BMALL_PRICE_HUNDRED_TO_TWO_HUNDRED", PieceFilters.HUNDRED2TWO_HUNDRED),
    ("BMALL_PRICE_OVER_TWO_HUNDRED", PieceFilters.OVER_TWO_HUNDRED),
)


def _float_env(key: str, default: float) -> float:
    value = os.environ.get(key)
    if not value:
        return default
    return float(value)


def _int_env(key: str, default: int) -> int:
    value = os.environ.get(key)
    if not value:
        return default
    return int(value)


def _bool_env(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    if value is None or not value.strip():
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _price_filters_from_env() -> tuple[PieceFilters, ...]:
    selected = tuple(
        price_filter
        for env_key, price_filter in PRICE_FILTER_ENV
        if _bool_env(env_key, True)
    )
    if not selected:
        raise SystemExit("At least one BMALL_PRICE_* range must be enabled")
    return selected


def _has_env_proxy() -> bool:
    return any(os.environ.get(key) for key in ENV_PROXY_KEYS)


def _log_effective_config(config: CrawlerConfig, *, reset_data: bool) -> None:
    price_labels = [
        PRICE_FILTER_LABELS[price_filter] for price_filter in config.price_filters
    ]
    logger.info(
        "Action crawl config: reset_data=%s, price_filters=%s, sleep_range=%.2f-%.2fs, "
        "max_retries=%s, retention_days=%s, data_dir=%s, bmall_proxy=%s, env_proxy=%s",
        reset_data,
        ", ".join(price_labels),
        config.sleep_range[0],
        config.sleep_range[1],
        config.max_retries,
        config.data_retention_days,
        config.data_dir,
        "set" if config.proxy else "unset",
        "set" if _has_env_proxy() else "unset",
    )


async def main() -> int:
    cookie_header = os.environ.get("BMALL_COOKIE", "").strip()
    if not cookie_header:
        raise SystemExit("BMALL_COOKIE is required")

    data_dir = Path(os.environ.get("BMALL_DATA_DIR", "Data"))
    sleep_min = _float_env("BMALL_SLEEP_MIN", 1.25)
    sleep_max = _float_env("BMALL_SLEEP_MAX", 1.5)
    reset_data = _bool_env("RESET_DATA", True)
    config = CrawlerConfig(
        cookie_header=cookie_header,
        data_dir=data_dir,
        proxy=os.environ.get("BMALL_PROXY") or None,
        trust_env=True,
        price_filters=_price_filters_from_env(),
        sleep_range=(sleep_min, sleep_max),
        max_retries=_int_env("BMALL_MAX_RETRIES", 10),
        dedupe_output=True,
        data_retention_days=_int_env("BMALL_DATA_RETENTION_DAYS", DATA_RETENTION_DAYS),
    )
    _log_effective_config(config, reset_data=reset_data)

    spider = BMallSpider(config)
    try:
        summary = await spider.fetch_all(reset=reset_data, restart=not reset_data)
    finally:
        await spider.close()

    print(
        "status={status} total_items={total} written_items={written} "
        "skipped_duplicates={duplicates} dropped_expired_items={expired} "
        "migrated_legacy_items={migrated} message={message}".format(
            status=summary.status,
            total=summary.total_items,
            written=summary.written_items,
            duplicates=summary.skipped_duplicates,
            expired=summary.dropped_expired_items,
            migrated=summary.migrated_legacy_items,
            message=summary.message,
        )
    )
    return 1 if summary.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
