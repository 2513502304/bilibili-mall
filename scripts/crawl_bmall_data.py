from __future__ import annotations

import asyncio
import os
from pathlib import Path

from bilibili_mall.interactive_crawler import BMallSpider, CrawlerConfig


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


async def main() -> int:
    cookie_header = os.environ.get("BMALL_COOKIE", "").strip()
    if not cookie_header:
        raise SystemExit("BMALL_COOKIE is required")

    data_dir = Path(os.environ.get("BMALL_DATA_DIR", "Data"))
    sleep_min = _float_env("BMALL_SLEEP_MIN", 1.25)
    sleep_max = _float_env("BMALL_SLEEP_MAX", 1.5)
    config = CrawlerConfig(
        cookie_header=cookie_header,
        data_dir=data_dir,
        proxy=os.environ.get("BMALL_PROXY") or None,
        trust_env=True,
        sleep_range=(sleep_min, sleep_max),
        max_retries=_int_env("BMALL_MAX_RETRIES", 10),
        dedupe_output=True,
    )

    spider = BMallSpider(config)
    try:
        summary = await spider.fetch_all(restart=True)
    finally:
        await spider.close()

    print(
        "status={status} total_items={total} written_items={written} "
        "skipped_duplicates={duplicates} message={message}".format(
            status=summary.status,
            total=summary.total_items,
            written=summary.written_items,
            duplicates=summary.skipped_duplicates,
            message=summary.message,
        )
    )
    return 1 if summary.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
