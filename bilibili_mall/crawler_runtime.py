from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import streamlit as st

from .interactive_crawler import (
    BMallSpider,
    CrawlerConfig,
    CrawlerControl,
    CrawlerRunSummary,
    clear_crawl_outputs,
)


@dataclass
class CrawlerRuntime:
    control: CrawlerControl
    thread: threading.Thread | None = None
    status: dict[str, Any] = field(default_factory=lambda: {"status": "idle"})
    lock: threading.Lock = field(default_factory=threading.Lock)
    logs: list[str] = field(default_factory=list)
    summary: CrawlerRunSummary | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def update(self, **payload: Any) -> None:
        with self.lock:
            self.status.update(payload)
            self.status["updated_at"] = time.time()

    def append_log(self, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {message}"
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-500:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            snapshot = dict(self.status)
            logs = list(self.logs)
        snapshot["alive"] = bool(self.thread and self.thread.is_alive())
        snapshot["paused"] = self.control.is_paused
        snapshot["started_at"] = self.started_at
        snapshot["finished_at"] = self.finished_at
        snapshot["summary"] = self.summary
        snapshot["error"] = self.error
        snapshot["logs"] = logs
        return snapshot


_CRAWLER_RUNTIME: CrawlerRuntime | None = None
_CRAWLER_RUNTIME_LOCK = threading.Lock()


def get_crawler_runtime() -> CrawlerRuntime:
    global _CRAWLER_RUNTIME
    with _CRAWLER_RUNTIME_LOCK:
        runtime = _CRAWLER_RUNTIME
        if not has_runtime_api(runtime):
            runtime = CrawlerRuntime(control=CrawlerControl())
            _CRAWLER_RUNTIME = runtime
        st.session_state["crawler_runtime"] = runtime
        return runtime


def has_runtime_api(runtime: Any) -> bool:
    return runtime is not None and all(
        hasattr(runtime, name)
        for name in (
            "control",
            "thread",
            "status",
            "lock",
            "update",
            "append_log",
            "snapshot",
        )
    )


def reset_crawler_runtime() -> CrawlerRuntime:
    global _CRAWLER_RUNTIME
    with _CRAWLER_RUNTIME_LOCK:
        runtime = CrawlerRuntime(control=CrawlerControl())
        _CRAWLER_RUNTIME = runtime
        st.session_state["crawler_runtime"] = runtime
        return runtime


class StreamlitRuntimeLogHandler(logging.Handler):
    def __init__(self, runtime: CrawlerRuntime) -> None:
        super().__init__(level=logging.INFO)
        self.runtime = runtime
        self.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.runtime.append_log(self.format(record))


def run_crawler_worker(
    runtime: CrawlerRuntime,
    config: CrawlerConfig,
    *,
    reset: bool,
    restart: bool,
) -> None:
    handler = StreamlitRuntimeLogHandler(runtime)
    crawler_logger = logging.getLogger("bilibili-mall")
    crawler_logger.addHandler(handler)

    async def _run() -> None:
        spider = BMallSpider(config)
        try:
            runtime.update(status="running", message="爬虫正在运行")
            runtime.append_log("INFO 已清空数据并重新启动爬虫" if reset else "INFO 爬虫已启动")
            summary = await spider.fetch_all(
                reset=reset,
                restart=restart,
                control=runtime.control,
                progress_callback=lambda payload: runtime.update(**payload),
            )
            runtime.summary = summary
            runtime.update(status=summary.status, message=summary.message)
            runtime.append_log(f"INFO {summary.message}")
        finally:
            await spider.close()

    try:
        asyncio.run(_run())
    except Exception as exc:
        runtime.error = f"{exc.__class__.__name__}: {exc}"
        runtime.update(status="failed", message=runtime.error)
        runtime.append_log(f"ERROR {runtime.error}")
    finally:
        crawler_logger.removeHandler(handler)
        runtime.finished_at = time.time()


def start_crawler(config: CrawlerConfig, *, reset: bool = False, restart: bool = False) -> None:
    global _CRAWLER_RUNTIME
    with _CRAWLER_RUNTIME_LOCK:
        current_runtime = _CRAWLER_RUNTIME
        if (
            has_runtime_api(current_runtime)
            and current_runtime.thread
            and current_runtime.thread.is_alive()
        ):
            current_runtime.append_log("WARNING 已有爬虫后台线程运行，忽略重复启动")
            current_runtime.update(status="running", message="已有爬虫正在运行")
            st.session_state["crawler_runtime"] = current_runtime
            return

        runtime = CrawlerRuntime(control=CrawlerControl())
        _CRAWLER_RUNTIME = runtime
        st.session_state["crawler_runtime"] = runtime
    runtime.update(status="starting", message="正在启动爬虫")
    runtime.append_log("INFO 正在创建爬虫后台线程")
    thread = threading.Thread(
        target=run_crawler_worker,
        args=(runtime, config),
        kwargs={"reset": reset, "restart": restart},
        daemon=True,
        name="bmall-crawler",
    )
    runtime.thread = thread
    thread.start()


def clear_existing_crawl_data(data_dir: Path, clear_data_cache: Callable[[], None]) -> None:
    asyncio.run(clear_crawl_outputs(data_dir, include_data=True))
    clear_data_cache()
    runtime = reset_crawler_runtime()
    runtime.update(status="idle", message="已清除现有数据和断点")
    runtime.append_log("INFO 已清除现有数据和断点")
