import asyncio
import hashlib
import os
import tempfile
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

BMALL_LIST_URL = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
BMALL_REFERER = "https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
ERROR_BACKOFF_MIN_SECONDS = 0.3
ERROR_BACKOFF_MAX_SECONDS = 3.0
PAUSE_POLL_SECONDS = 0.25
RECORDED_AT_FIELD = "recordedAt"
DATA_RETENTION_DAYS = 15
SECONDS_PER_DAY = 24 * 60 * 60


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


def error_backoff_seconds(hit_counts: int) -> float:
    return min(
        ERROR_BACKOFF_MAX_SECONDS,
        ERROR_BACKOFF_MIN_SECONDS * 2 ** max(hit_counts - 1, 0),
    )


def parse_recorded_at(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        timestamp = int(value)
        return timestamp if timestamp > 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            timestamp = int(float(stripped))
        except ValueError:
            return None
        return timestamp if timestamp > 0 else None
    return None


def item_with_recorded_at(item: dict[str, Any], recorded_at: int) -> dict[str, Any]:
    stamped_item = dict(item)
    stamped_item[RECORDED_AT_FIELD] = recorded_at
    return stamped_item


def normalize_recorded_at(
    item: dict[str, Any],
    *,
    fallback_recorded_at: int,
) -> tuple[dict[str, Any], int, bool]:
    recorded_at = parse_recorded_at(item.get(RECORDED_AT_FIELD))
    if recorded_at is not None:
        return item, recorded_at, False
    return item_with_recorded_at(item, fallback_recorded_at), fallback_recorded_at, True


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
    data_retention_days: int = DATA_RETENTION_DAYS

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort_types", _enum_tuple(SortType, self.sort_types))
        object.__setattr__(self, "price_filters", _enum_tuple(PieceFilters, self.price_filters))
        object.__setattr__(
            self,
            "discount_filters",
            _enum_tuple(DiscountFilters, self.discount_filters),
        )
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(
            self,
            "data_retention_days",
            max(1, int(self.data_retention_days)),
        )

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
    dropped_expired_items: int = 0
    migrated_legacy_items: int = 0
    request_index: int = 0
    next_id: str | None = None
    message: str = ""


@dataclass(frozen=True)
class DataRetentionSummary:
    kept_items: int = 0
    dropped_expired_items: int = 0
    migrated_legacy_items: int = 0


@dataclass
class CrawlRunContext:
    requests: list[CrawlRequest]
    fingerprint: str
    request_index: int
    next_id: str | None
    total_items: int
    seen_item_ids: set[str]
    written_items: int = 0
    skipped_duplicates: int = 0
    dropped_expired_items: int = 0
    migrated_legacy_items: int = 0
    started_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class CrawlPage:
    items: list[dict[str, Any]]
    next_id: str | None


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
        context = await self._prepare_run(reset=reset, restart=restart)

        for index in range(context.request_index, len(context.requests)):
            request = context.requests[index]
            if index != context.request_index:
                context.next_id = None
            hit_counts = 0

            while True:
                if await self._should_stop(control, progress_callback, index, context.next_id):
                    return self._summary(
                        status="stopped",
                        context=context,
                        request_index=index,
                        message="用户停止了爬虫",
                    )

                try:
                    page = await self._fetch_page(request, context.next_id)
                    hit_counts = 0
                    written_count = await self._store_page_items(page, context)
                    logger.info(
                        "Fetched %s items, wrote %s new items, total %s items",
                        len(page.items),
                        written_count,
                        context.total_items,
                    )

                    await self._save_running_state(context, index)
                    self._emit_running_progress(
                        progress_callback,
                        context=context,
                        request=request,
                        request_index=index,
                        fetched_items=len(page.items),
                    )

                    if context.next_id is None:
                        break

                except Exception as exc:
                    logger.error(f"{exc.__class__.__name__} - {exc}")
                    hit_counts += 1
                    await asyncio.sleep(error_backoff_seconds(hit_counts))
                    self._emit_error_progress(
                        progress_callback,
                        context=context,
                        request=request,
                        request_index=index,
                        error=f"{exc.__class__.__name__}: {exc}",
                        hit_counts=hit_counts,
                    )
                    if hit_counts >= self.config.max_retries:
                        logger.critical("Too many http errors, stop fetching")
                        return self._summary(
                            status="failed",
                            context=context,
                            request_index=index,
                            message=f"连续错误达到 {self.config.max_retries} 次，已停止",
                        )

            await self._save_completed_request_state(context, index)

        logger.info(f"All data fetched, total {context.total_items} items")
        return self._summary(
            status="completed",
            context=context,
            request_index=len(context.requests),
            message="抓取完成",
        )

    async def close(self) -> None:
        await self.session.close()

    async def _prepare_run(self, *, reset: bool, restart: bool) -> CrawlRunContext:
        config = self.config
        await aioos.makedirs(str(config.data_dir), exist_ok=True)
        if reset:
            await clear_crawl_outputs(config.data_dir, include_data=True)
        elif restart:
            await clear_crawl_outputs(config.data_dir, include_data=False)
        retention = await self._apply_data_retention()

        fingerprint = config.fingerprint()
        state = await self._load_state()
        if state.get("fingerprint") != fingerprint:
            state = {}

        return CrawlRunContext(
            requests=config.build_requests(),
            fingerprint=fingerprint,
            request_index=int(state.get("request_index") or 0),
            next_id=state.get("next_id"),
            total_items=retention.kept_items,
            seen_item_ids=(
                await self._load_seen_item_ids() if config.dedupe_output else set()
            ),
            dropped_expired_items=retention.dropped_expired_items,
            migrated_legacy_items=retention.migrated_legacy_items,
        )

    async def _fetch_page(self, request: CrawlRequest, next_id: str | None) -> CrawlPage:
        await asyncio.sleep(np.random.uniform(*self.config.sleep_range))
        response: Response = await self.session.post(
            BMALL_LIST_URL,
            json=request.to_payload(next_id),
            referer=BMALL_REFERER,
            cookies=self.config.cookies,
        )
        response.raise_for_status()

        payload: dict[str, Any] = response.json()
        return CrawlPage(
            items=payload["data"]["data"],
            next_id=payload["data"]["nextId"],
        )

    async def _store_page_items(
        self,
        page: CrawlPage,
        context: CrawlRunContext,
    ) -> int:
        context.next_id = page.next_id
        new_items, duplicate_count = self._dedupe_items(page.items, context.seen_item_ids)
        context.skipped_duplicates += duplicate_count

        if new_items:
            recorded_at = int(time.time())
            stored_items = [
                item_with_recorded_at(item, recorded_at) for item in new_items
            ]
            async with aiofiles.open(self.config.data_path, "ab") as f:
                await f.write(
                    b"".join(orjson.dumps(item) + b"\n" for item in stored_items)
                )

        context.total_items += len(new_items)
        context.written_items += len(new_items)
        return len(new_items)

    async def _save_running_state(self, context: CrawlRunContext, request_index: int) -> None:
        await self._save_next_id(context.next_id)
        await self._save_state(
            {
                "fingerprint": context.fingerprint,
                "config": self.config.to_state(),
                "request_index": request_index,
                "next_id": context.next_id,
                "completed": False,
                "updated_at": time.time(),
            }
        )

    async def _save_completed_request_state(
        self,
        context: CrawlRunContext,
        request_index: int,
    ) -> None:
        await self._save_state(
            {
                "fingerprint": context.fingerprint,
                "config": self.config.to_state(),
                "request_index": request_index + 1,
                "next_id": None,
                "completed": request_index + 1 >= len(context.requests),
                "updated_at": time.time(),
            }
        )

    def _emit_running_progress(
        self,
        progress_callback: ProgressCallback | None,
        *,
        context: CrawlRunContext,
        request: CrawlRequest,
        request_index: int,
        fetched_items: int,
    ) -> None:
        self._emit_progress(
            progress_callback,
            status="running",
            request_index=request_index,
            request_count=len(context.requests),
            sort_type=request.sort_type.value,
            next_id=context.next_id,
            fetched_items=fetched_items,
            written_items=context.written_items,
            skipped_duplicates=context.skipped_duplicates,
            total_items=context.total_items,
            elapsed_seconds=time.time() - context.started_at,
        )

    def _emit_error_progress(
        self,
        progress_callback: ProgressCallback | None,
        *,
        context: CrawlRunContext,
        request: CrawlRequest,
        request_index: int,
        error: str,
        hit_counts: int,
    ) -> None:
        self._emit_progress(
            progress_callback,
            status="error",
            request_index=request_index,
            request_count=len(context.requests),
            sort_type=request.sort_type.value,
            next_id=context.next_id,
            error=error,
            hit_counts=hit_counts,
            total_items=context.total_items,
        )

    def _summary(
        self,
        *,
        status: str,
        context: CrawlRunContext,
        request_index: int,
        message: str,
    ) -> CrawlerRunSummary:
        return CrawlerRunSummary(
            status=status,
            total_items=context.total_items,
            written_items=context.written_items,
            skipped_duplicates=context.skipped_duplicates,
            dropped_expired_items=context.dropped_expired_items,
            migrated_legacy_items=context.migrated_legacy_items,
            request_index=request_index,
            next_id=context.next_id,
            message=message,
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

    async def _apply_data_retention(self) -> DataRetentionSummary:
        if not await aioos.path.exists(self.config.data_path):
            return DataRetentionSummary()

        now = int(time.time())
        cutoff = now - self.config.data_retention_days * SECONDS_PER_DAY
        kept_items = 0
        dropped_expired_items = 0
        migrated_legacy_items = 0
        changed = False

        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            dir=self.config.data_path.parent,
            prefix=".bmall_all_data.",
            suffix=".jsonl",
        )
        temp_path = Path(temp_file.name)
        temp_file.close()

        try:
            async with (
                aiofiles.open(self.config.data_path, "rb") as source,
                aiofiles.open(temp_path, "wb") as destination,
            ):
                async for line in source:
                    if not line.strip():
                        changed = True
                        continue
                    try:
                        item = orjson.loads(line)
                    except orjson.JSONDecodeError:
                        changed = True
                        continue
                    if not isinstance(item, dict):
                        changed = True
                        continue

                    item, recorded_at, migrated = normalize_recorded_at(
                        item,
                        fallback_recorded_at=now,
                    )
                    if recorded_at < cutoff:
                        dropped_expired_items += 1
                        changed = True
                        continue
                    if migrated:
                        migrated_legacy_items += 1
                        changed = True

                    kept_items += 1
                    await destination.write(orjson.dumps(item) + b"\n")

            if changed:
                await aioos.replace(temp_path, self.config.data_path)
            else:
                await aioos.remove(temp_path)
        except Exception:
            if await aioos.path.exists(temp_path):
                await aioos.remove(temp_path)
            raise

        if dropped_expired_items or migrated_legacy_items:
            logger.info(
                "Prepared existing data: kept %s items, dropped %s expired items, "
                "migrated %s legacy items",
                kept_items,
                dropped_expired_items,
                migrated_legacy_items,
            )

        return DataRetentionSummary(
            kept_items=kept_items,
            dropped_expired_items=dropped_expired_items,
            migrated_legacy_items=migrated_legacy_items,
        )

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
            await asyncio.sleep(PAUSE_POLL_SECONDS)
        return control.is_stopped

    def _emit_progress(self, progress_callback: ProgressCallback | None, **payload: Any) -> None:
        if progress_callback is None:
            return
        progress_callback(payload)
