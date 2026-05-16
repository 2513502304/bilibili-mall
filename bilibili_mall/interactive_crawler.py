import asyncio
import hashlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import aiofiles
import numpy as np
import orjson
from aiofiles import os as aioos
from curl_cffi import AsyncSession, Response

from .crawler_options import ENV_PROXY_KEYS, DiscountFilters, PieceFilters, SortType
from .utils import logger


def crawl_data_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "bmall_all_data.jsonl"


def crawl_next_id_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "bmall_next_id.txt"


def crawl_state_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "bmall_crawl_state.json"


def read_crawl_state(data_dir: Path | str) -> dict[str, Any]:
    path = crawl_state_path(data_dir)
    if not path.exists():
        return {}
    try:
        return orjson.loads(path.read_bytes())
    except orjson.JSONDecodeError:
        return {}


async def clear_crawl_outputs(data_dir: Path | str, *, include_data: bool) -> None:
    paths = [crawl_next_id_path(data_dir), crawl_state_path(data_dir)]
    if include_data:
        paths.insert(0, crawl_data_path(data_dir))

    for path in paths:
        if await aioos.path.exists(path):
            await aioos.remove(path)


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookies = {}
    for item in cookie_header.split(";"):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        if key:
            cookies[key] = value.strip()
    return cookies


def detect_env_proxy() -> str | None:
    for key in ENV_PROXY_KEYS:
        value = os.environ.get(key)
        if value:
            return value
    return None


def _enum_tuple(enum_type: type[Enum], values: tuple[Enum | str, ...]) -> tuple[Enum, ...]:
    result = []
    for value in values:
        if isinstance(value, enum_type):
            result.append(value)
        else:
            result.append(enum_type[value] if value in enum_type.__members__ else enum_type(value))
    return tuple(result)


def _flatten_filter_values(values: tuple[PieceFilters | DiscountFilters, ...]) -> list[str]:
    flattened: list[str] = []
    for value in values:
        flattened.extend(value.value)
    return flattened


@dataclass(frozen=True)
class CrawlRequest:
    sort_type: SortType
    price_filters: list[str]
    discount_filters: list[str]

    def to_payload(self, next_id: str | None) -> dict[str, Any]:
        return {
            "nextId": next_id,
            "sortType": self.sort_type.value,
            "priceFilters": self.price_filters or None,
            "discountFilters": self.discount_filters or None,
        }


@dataclass(frozen=True)
class CrawlerConfig:
    sort_types: tuple[SortType | str, ...] = (SortType.PRICE_DESC,)
    price_filters: tuple[PieceFilters | str, ...] = field(default_factory=lambda: tuple(PieceFilters))
    discount_filters: tuple[DiscountFilters | str, ...] = ()
    cookie_header: str = field(default_factory=lambda: os.environ.get("BMALL_COOKIE", ""))
    data_dir: Path | str = Path("./Data")
    proxy: str | None = None
    trust_env: bool = True
    sleep_range: tuple[float, float] = (1.25, 1.5)
    error_extra_sleep_range: tuple[float, float] = (0.2, 0.3)
    max_retries: int = 10
    dedupe_output: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort_types", _enum_tuple(SortType, self.sort_types))
        object.__setattr__(self, "price_filters", _enum_tuple(PieceFilters, self.price_filters))
        object.__setattr__(
            self,
            "discount_filters",
            _enum_tuple(DiscountFilters, self.discount_filters),
        )
        object.__setattr__(self, "data_dir", Path(self.data_dir))

    @property
    def data_path(self) -> Path:
        return crawl_data_path(self.data_dir)

    @property
    def legacy_next_id_path(self) -> Path:
        return crawl_next_id_path(self.data_dir)

    @property
    def state_path(self) -> Path:
        return crawl_state_path(self.data_dir)

    @property
    def cookies(self) -> dict[str, str]:
        return parse_cookie_header(self.cookie_header)

    def build_requests(self) -> list[CrawlRequest]:
        price_filters = _flatten_filter_values(self.price_filters)
        discount_filters = _flatten_filter_values(self.discount_filters)
        return [
            CrawlRequest(
                sort_type=sort_type,
                price_filters=price_filters,
                discount_filters=discount_filters,
            )
            for sort_type in self.sort_types
        ]

    def fingerprint(self) -> str:
        payload = {
            "sortTypes": [sort_type.value for sort_type in self.sort_types],
            "priceFilters": _flatten_filter_values(self.price_filters),
            "discountFilters": _flatten_filter_values(self.discount_filters),
        }
        return hashlib.sha256(orjson.dumps(payload)).hexdigest()

    def to_state(self) -> dict[str, list[str]]:
        return {
            "sort_types": [sort_type.name for sort_type in self.sort_types],
            "price_filters": [price_filter.name for price_filter in self.price_filters],
            "discount_filters": [
                discount_filter.name for discount_filter in self.discount_filters
            ],
        }


@dataclass
class CrawlerRunSummary:
    status: str
    total_items: int = 0
    written_items: int = 0
    skipped_duplicates: int = 0
    request_index: int = 0
    next_id: str | None = None
    message: str = ""


class CrawlerControl:
    def __init__(self) -> None:
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()

    def pause(self) -> None:
        self.pause_event.set()

    def resume(self) -> None:
        self.pause_event.clear()

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def is_paused(self) -> bool:
        return self.pause_event.is_set()

    @property
    def is_stopped(self) -> bool:
        return self.stop_event.is_set()


ProgressCallback = Callable[[dict[str, Any]], None]


class BMallSpider:
    def __init__(self, config: CrawlerConfig | None = None):
        self.config = config or CrawlerConfig()
        self.session = AsyncSession(
            max_clients=12,
            base_url=None,
            timeout=30,
            proxy=self.config.proxy,
            trust_env=self.config.trust_env,
            allow_redirects=True,
            impersonate="chrome",
            default_headers=True,
            default_encoding="utf-8",
        )

    async def fetch_all(
        self,
        *,
        reset: bool = False,
        restart: bool = False,
        control: CrawlerControl | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> CrawlerRunSummary:
        config = self.config
        await aioos.makedirs(str(config.data_dir), exist_ok=True)
        if reset:
            await clear_crawl_outputs(config.data_dir, include_data=True)
        elif restart:
            await clear_crawl_outputs(config.data_dir, include_data=False)

        requests = config.build_requests()
        state = await self._load_state()
        fingerprint = config.fingerprint()
        if state.get("fingerprint") != fingerprint:
            state = {}

        request_index = int(state.get("request_index") or 0)
        next_id = state.get("next_id")
        total_items = await self._count_existing_items()
        seen_item_ids = await self._load_seen_item_ids() if config.dedupe_output else set()
        written_items = 0
        skipped_duplicates = 0
        started_at = time.time()

        url = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
        referer = "https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
        cookies = config.cookies

        for index in range(request_index, len(requests)):
            request = requests[index]
            if index != request_index:
                next_id = None
            hit_counts = 0

            while True:
                if await self._should_stop(control, progress_callback, index, next_id):
                    return CrawlerRunSummary(
                        status="stopped",
                        total_items=total_items,
                        written_items=written_items,
                        skipped_duplicates=skipped_duplicates,
                        request_index=index,
                        next_id=next_id,
                        message="用户停止了爬虫",
                    )

                try:
                    await asyncio.sleep(np.random.uniform(*config.sleep_range))

                    response: Response = await self.session.post(
                        url,
                        json=request.to_payload(next_id),
                        referer=referer,
                        cookies=cookies,
                    )
                    response.raise_for_status()

                    if hit_counts > 0:
                        hit_counts = 0

                    json_: dict[str, Any] = response.json()
                    data: list[dict[str, Any]] = json_["data"]["data"]
                    next_id = json_["data"]["nextId"]
                    new_data, duplicate_count = self._dedupe_items(data, seen_item_ids)
                    skipped_duplicates += duplicate_count

                    if new_data:
                        async with aiofiles.open(config.data_path, "ab") as f:
                            await f.write(
                                b"".join(orjson.dumps(item) + b"\n" for item in new_data)
                            )

                    total_items += len(new_data)
                    written_items += len(new_data)
                    logger.info(
                        "Fetched %s items, wrote %s new items, total %s items",
                        len(data),
                        len(new_data),
                        total_items,
                    )

                    await self._save_next_id(next_id)
                    await self._save_state(
                        {
                            "fingerprint": fingerprint,
                            "config": config.to_state(),
                            "request_index": index,
                            "next_id": next_id,
                            "completed": False,
                            "updated_at": time.time(),
                        }
                    )
                    self._emit_progress(
                        progress_callback,
                        status="running",
                        request_index=index,
                        request_count=len(requests),
                        sort_type=request.sort_type.value,
                        next_id=next_id,
                        fetched_items=len(data),
                        written_items=written_items,
                        skipped_duplicates=skipped_duplicates,
                        total_items=total_items,
                        elapsed_seconds=time.time() - started_at,
                    )

                    if next_id is None:
                        break

                except Exception as exc:
                    logger.error(f"{exc.__class__.__name__} - {exc}")
                    await asyncio.sleep(np.random.uniform(*config.error_extra_sleep_range))
                    hit_counts += 1
                    self._emit_progress(
                        progress_callback,
                        status="error",
                        request_index=index,
                        request_count=len(requests),
                        sort_type=request.sort_type.value,
                        next_id=next_id,
                        error=f"{exc.__class__.__name__}: {exc}",
                        hit_counts=hit_counts,
                        total_items=total_items,
                    )
                    if hit_counts >= config.max_retries:
                        logger.critical("Too many http errors, stop fetching")
                        return CrawlerRunSummary(
                            status="failed",
                            total_items=total_items,
                            written_items=written_items,
                            skipped_duplicates=skipped_duplicates,
                            request_index=index,
                            next_id=next_id,
                            message=f"连续错误达到 {config.max_retries} 次，已停止",
                        )

            await self._save_state(
                {
                    "fingerprint": fingerprint,
                    "config": config.to_state(),
                    "request_index": index + 1,
                    "next_id": None,
                    "completed": index + 1 >= len(requests),
                    "updated_at": time.time(),
                }
            )

        logger.info(f"All data fetched, total {total_items} items")
        return CrawlerRunSummary(
            status="completed",
            total_items=total_items,
            written_items=written_items,
            skipped_duplicates=skipped_duplicates,
            request_index=len(requests),
            next_id=None,
            message="抓取完成",
        )

    async def _load_state(self) -> dict[str, Any]:
        if not await aioos.path.exists(self.config.state_path):
            return {}
        async with aiofiles.open(self.config.state_path, "rb") as f:
            try:
                return orjson.loads(await f.read())
            except orjson.JSONDecodeError:
                return {}

    async def _save_state(self, state: dict[str, Any]) -> None:
        async with aiofiles.open(self.config.state_path, "wb") as f:
            await f.write(orjson.dumps(state, option=orjson.OPT_INDENT_2))

    async def _save_next_id(self, next_id: str | None) -> None:
        async with aiofiles.open(self.config.legacy_next_id_path, "w", encoding="utf-8") as f:
            await f.write(f"{next_id}")

    async def _count_existing_items(self) -> int:
        if not await aioos.path.exists(self.config.data_path):
            return 0
        total = 0
        async with aiofiles.open(self.config.data_path, "rb") as f:
            async for _ in f:
                total += 1
        return total

    async def _load_seen_item_ids(self) -> set[str]:
        if not await aioos.path.exists(self.config.data_path):
            return set()
        seen_item_ids = set()
        async with aiofiles.open(self.config.data_path, "rb") as f:
            async for line in f:
                try:
                    item = orjson.loads(line)
                except orjson.JSONDecodeError:
                    continue
                item_id = item.get("c2cItemsId")
                if item_id is not None:
                    seen_item_ids.add(str(item_id))
        return seen_item_ids

    def _dedupe_items(
        self,
        items: list[dict[str, Any]],
        seen_item_ids: set[str],
    ) -> tuple[list[dict[str, Any]], int]:
        if not self.config.dedupe_output:
            return items, 0

        new_items = []
        duplicate_count = 0
        for item in items:
            item_id = item.get("c2cItemsId")
            if item_id is None:
                new_items.append(item)
                continue
            key = str(item_id)
            if key in seen_item_ids:
                duplicate_count += 1
                continue
            seen_item_ids.add(key)
            new_items.append(item)
        return new_items, duplicate_count

    async def _should_stop(
        self,
        control: CrawlerControl | None,
        progress_callback: ProgressCallback | None,
        request_index: int,
        next_id: str | None,
    ) -> bool:
        if control is None:
            return False
        while control.is_paused and not control.is_stopped:
            self._emit_progress(
                progress_callback,
                status="paused",
                request_index=request_index,
                next_id=next_id,
            )
            await asyncio.sleep(0.25)
        return control.is_stopped

    def _emit_progress(self, progress_callback: ProgressCallback | None, **payload: Any) -> None:
        if progress_callback is None:
            return
        progress_callback(payload)
