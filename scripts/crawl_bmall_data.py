from __future__ import annotations

import asyncio
import os
from pathlib import Path

from bilibili_mall.interactive_crawler import (
    DATA_RETENTION_DAYS,
    BMallSpider,
    CrawlerConfig,
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
        sleep_range=(sleep_min, sleep_max),
        max_retries=_int_env("BMALL_MAX_RETRIES", 10),
        dedupe_output=True,
        data_retention_days=_int_env("BMALL_DATA_RETENTION_DAYS", DATA_RETENTION_DAYS),
    )

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
