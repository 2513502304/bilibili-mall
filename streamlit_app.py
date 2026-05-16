from __future__ import annotations

import asyncio
import html
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson
import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from bilibili_mall.app_config import configured_value, slider_bounds
from bilibili_mall.interactive_crawler import (
    CrawlerConfig,
    CrawlerControl,
    CrawlerRunSummary,
    BMallSpider,
    clear_crawl_outputs,
    detect_env_proxy,
    read_crawl_state,
)
from bilibili_mall.crawler_options import (
    DISCOUNT_FILTER_LABELS,
    PRICE_FILTER_LABELS,
    SORT_TYPE_LABELS,
    SortType,
)


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "Data" / "bmall_all_data.jsonl"
DATA_SCHEMA_VERSION = 2
DETAIL_URL = (
    "https://mall.bilibili.com/neul-next/index.html"
    "?page=magic-market_detail&noTitleBar=1&itemsId={items_id}&from=market_index"
)

LOG_VIEWER = st.components.v2.component(
    "crawler_log_viewer",
    html='<div class="log-shell"><pre id="crawler-log"></pre></div>',
    css="""
.log-shell {
    background: #0f172a;
    border: 1px solid rgba(148, 163, 184, 0.35);
    border-radius: 8px;
    height: 320px;
    overflow: auto;
}

#crawler-log {
    color: #dbeafe;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    font-size: 0.82rem;
    line-height: 1.5;
    margin: 0;
    padding: 0.85rem;
    white-space: pre-wrap;
    word-break: break-word;
}
""",
    js="""
const followByElement = new WeakMap()

export default function (component) {
  const { data, parentElement } = component
  const shell = parentElement.querySelector(".log-shell")
  const log = parentElement.querySelector("#crawler-log")
  if (!shell || !log) return

  if (!followByElement.has(shell)) {
    followByElement.set(shell, true)
  }

  shell.onscroll = () => {
    const distanceFromBottom = shell.scrollHeight - shell.scrollTop - shell.clientHeight
    followByElement.set(shell, distanceFromBottom < 24)
  }

  const nextText = (data && data.text) || ""
  if (log.textContent !== nextText) {
    const shouldFollow = followByElement.get(shell)
    log.textContent = nextText
    if (shouldFollow) {
      requestAnimationFrame(() => {
        shell.scrollTop = shell.scrollHeight
      })
    }
  }
}
""",
)


st.set_page_config(
    page_title="Bilibili mall finder",
    page_icon=":material/shopping_bag:",
    layout="wide",
)


st.markdown(
    """
    <style>
    :root {
        --bm-border: rgba(15, 23, 42, 0.10);
        --bm-muted: #64748b;
        --bm-ink: #0f172a;
        --bm-soft: #f8fafc;
        --bm-pink: #fb7299;
        --bm-teal: #00a1d6;
    }

    .block-container {
        padding-top: 2.25rem;
        padding-bottom: 2rem;
    }

    [data-testid="stMetric"] {
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        border: 1px solid var(--bm-border);
        border-radius: 10px;
        padding: 1rem 1rem 0.85rem;
    }

    [data-testid="stTextInput"] [data-testid="InputInstructions"] {
        display: none;
    }

    .mall-header {
        margin-bottom: 0.75rem;
    }

    .mall-kicker {
        color: var(--bm-teal);
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0;
        margin-bottom: 0.35rem;
    }

    .mall-title {
        color: var(--bm-ink);
        font-size: 2.15rem;
        font-weight: 760;
        line-height: 1.12;
        margin: 0;
    }

    .mall-subtitle {
        color: var(--bm-muted);
        font-size: 0.98rem;
        margin-top: 0.55rem;
        max-width: 820px;
    }

    .result-title {
        color: var(--bm-ink);
        font-size: 1.03rem;
        font-weight: 700;
        line-height: 1.35;
        margin: 0 0 0.35rem;
    }

    .result-detail {
        color: var(--bm-muted);
        font-size: 0.86rem;
        line-height: 1.35;
        margin: 0.2rem 0 0.6rem;
    }

    .price {
        color: var(--bm-pink);
        font-size: 1.32rem;
        font-weight: 780;
        line-height: 1.1;
        margin-bottom: 0.2rem;
    }

    .market {
        color: var(--bm-muted);
        font-size: 0.82rem;
    }

    .meta-line {
        color: var(--bm-muted);
        font-size: 0.84rem;
        line-height: 1.5;
    }

    .badge-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.35rem;
        margin-top: 0.45rem;
    }

    .soft-badge {
        background: #eff6ff;
        border: 1px solid #dbeafe;
        border-radius: 999px;
        color: #1d4ed8;
        display: inline-flex;
        font-size: 0.75rem;
        font-weight: 650;
        padding: 0.16rem 0.52rem;
        white-space: nowrap;
    }

    .pink-badge {
        background: #fff1f5;
        border-color: #ffd6e3;
        color: #be185d;
    }

    .thumb-frame {
        align-items: center;
        background: #f1f5f9;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        display: flex;
        height: 118px;
        justify-content: center;
        overflow: hidden;
        width: 118px;
    }

    .thumb-frame img {
        height: 100%;
        object-fit: cover;
        width: 100%;
    }

    .thumb-empty {
        color: #94a3b8;
        font-size: 0.78rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _read_jsonl_snapshot(path: str) -> pd.DataFrame:
    raw = Path(path).read_bytes()
    lines = raw.splitlines()
    if not lines:
        return pd.DataFrame()

    rows: list[Any] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            rows.append(orjson.loads(line))
        except orjson.JSONDecodeError:
            if index == len(lines) - 1 and not raw.endswith((b"\n", b"\r")):
                break
            raise
    return pd.DataFrame.from_records(rows)


def _first_detail_value(details: Any, key: str) -> Any:
    if isinstance(details, list) and details and isinstance(details[0], dict):
        return details[0].get(key)
    return None


def _normalize_image_url(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _normalize_text_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _has_hidden_detail(details: Any) -> bool:
    if not isinstance(details, list):
        return False
    return any(isinstance(item, dict) and item.get("isHidden") for item in details)


def _format_yuan(value: Any) -> str:
    if pd.isna(value):
        return "¥-"
    value = float(value)
    if value.is_integer():
        return f"¥{value:,.0f}"
    return f"¥{value:,.2f}"


def _prepare_items(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    df["rowNumber"] = range(len(df))
    df["imageUrl"] = df["detailDtoList"].apply(
        lambda details: _normalize_image_url(_first_detail_value(details, "img"))
    )
    df["hasHiddenDetail"] = df["detailDtoList"].apply(_has_hidden_detail)
    df["detailName"] = df["detailDtoList"].apply(
        lambda details: _first_detail_value(details, "name")
    )
    df["c2cItemsLink"] = df["c2cItemsId"].apply(
        lambda item_id: DETAIL_URL.format(items_id=item_id)
    )
    df["priceYuan"] = pd.to_numeric(df["price"], errors="coerce") / 100
    df["marketYuan"] = pd.to_numeric(df["showMarketPrice"], errors="coerce")
    df["discountPct"] = (1 - df["priceYuan"] / df["marketYuan"]) * 100
    df.loc[df["marketYuan"].le(0) | df["marketYuan"].isna(), "discountPct"] = pd.NA
    df["searchText"] = (
        df["c2cItemsName"].fillna("")
        + " "
        + df["detailName"].fillna("")
        + " "
        + df["uname"].fillna("")
    )
    df["titleKey"] = df["c2cItemsName"].apply(_normalize_text_key)
    df["detailKey"] = df["detailName"].apply(_normalize_text_key)
    df["primaryItemKey"] = df["detailKey"].where(df["detailKey"].ne(""), df["titleKey"])
    df["titleDuplicateCount"] = df.groupby("titleKey")["titleKey"].transform("size")
    return df


@st.cache_data(show_spinner=False, max_entries=3)
def load_items(
    path: str,
    mtime_ns: int,
    size: int,
    schema_version: int,
) -> pd.DataFrame:
    _ = (mtime_ns, size, schema_version)
    return _prepare_items(_read_jsonl_snapshot(path))


@st.cache_data(show_spinner=False, max_entries=3, ttl="10m")
def load_items_from_url(url: str, schema_version: int) -> pd.DataFrame:
    _ = schema_version
    return _prepare_items(pd.read_json(url, lines=True))


def configured_data_url() -> str:
    return configured_value(
        "BMALL_DATA_URL",
        env=os.environ,
        secret_getter=st.secrets.get,
        missing_secret_errors=(StreamlitSecretNotFoundError,),
    )


def filter_items(
    df: pd.DataFrame,
    query: str,
    price_range: tuple[int, int],
    quantity_mode: str,
    product_type: str,
    hidden_mode: str,
    search_mode: str,
    with_image: bool,
    min_discount: int,
) -> pd.DataFrame:
    result = df.copy()
    query = query.strip()

    if query:
        matches = []
        for token in re.split(r"\s+", query):
            matches.append(
                result["searchText"].str.contains(re.escape(token), case=False, na=False)
            )
        if search_mode == "任一关键词":
            result = result[pd.concat(matches, axis=1).any(axis=1)]
        else:
            result = result[pd.concat(matches, axis=1).all(axis=1)]

    result = result[
        result["priceYuan"].between(price_range[0], price_range[1], inclusive="both")
    ]

    if quantity_mode == "单件":
        result = result[result["totalItemsCount"].eq(1)]
    elif quantity_mode == "多件":
        result = result[result["totalItemsCount"].gt(1)]

    if product_type == "普通商品":
        result = result[result["type"].eq(1)]
    elif product_type == "福袋":
        result = result[result["type"].eq(2)]

    if hidden_mode == "排除隐藏信息":
        result = result[~result["hasHiddenDetail"]]
    elif hidden_mode == "只看隐藏信息":
        result = result[result["hasHiddenDetail"]]

    if with_image:
        result = result[result["imageUrl"].notna()]
    if min_discount > 0:
        result = result[result["discountPct"].fillna(-1).ge(min_discount)]

    return result


def sort_items(df: pd.DataFrame, sort_mode: str) -> pd.DataFrame:
    sort_columns = {
        "价格从低到高": ["priceYuan", "c2cItemsId"],
        "折扣力度优先": ["discountPct", "priceYuan"],
        "库存数量优先": ["totalItemsCount", "priceYuan"],
        "最新抓取优先": ["rowNumber"],
    }
    ascending = {
        "价格从低到高": [True, False],
        "折扣力度优先": [False, True],
        "库存数量优先": [False, True],
        "最新抓取优先": [False],
    }
    return df.sort_values(
        sort_columns[sort_mode],
        ascending=ascending[sort_mode],
        na_position="last",
    )


def reduce_duplicates(
    df: pd.DataFrame,
    duplicate_mode: str,
    duplicate_key_mode: str,
    duplicate_keep_n: int,
) -> pd.DataFrame:
    if duplicate_mode == "不过滤重复":
        return df

    key_column = {
        "按商品标题": "titleKey",
        "按首个明细商品": "primaryItemKey",
    }[duplicate_key_mode]
    keep_n = 1 if duplicate_mode == "每个商品只保留最低价" else duplicate_keep_n
    ranked = df.sort_values(
        [key_column, "priceYuan", "rowNumber"],
        ascending=[True, True, False],
        na_position="last",
    )
    return (
        ranked.groupby(key_column, sort=False, dropna=False)
        .head(keep_n)
        .reset_index(drop=True)
    )


def paginate(df: pd.DataFrame, page: int, page_size: int) -> pd.DataFrame:
    start = (page - 1) * page_size
    end = start + page_size
    return df.iloc[start:end]


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


def clear_existing_crawl_data() -> None:
    asyncio.run(clear_crawl_outputs(ROOT / "Data", include_data=True))
    load_items.clear()
    runtime = reset_crawler_runtime()
    runtime.update(status="idle", message="已清除现有数据和断点")
    runtime.append_log("INFO 已清除现有数据和断点")


def enum_labels(options: dict[Any, str]) -> list[str]:
    return list(options.values())


def reverse_lookup(options: dict[Any, str], labels: list[str]) -> tuple[Any, ...]:
    reverse = {label: key for key, label in options.items()}
    return tuple(reverse[label] for label in labels if label in reverse)


def labels_for_option_names(options: dict[Any, str], names: list[str] | None) -> list[str]:
    if not names:
        return []
    return [label for option, label in options.items() if option.name in names]


def render_enum_pills(
    title: str,
    options: dict[Any, str],
    key_prefix: str,
    default_labels: list[str],
) -> tuple[Any, ...]:
    labels = enum_labels(options)
    selected_labels = st.pills(
        title,
        labels,
        selection_mode="multi",
        default=[label for label in default_labels if label in labels],
        key=f"{key_prefix}_multi",
    )
    return reverse_lookup(options, list(selected_labels or []))


def render_crawler_status(runtime: CrawlerRuntime) -> None:
    snapshot = runtime.snapshot()
    status = snapshot.get("status", "idle")
    alive = snapshot["alive"]
    paused = snapshot["paused"]
    label = {
        "idle": "未运行",
        "running": "运行中",
        "paused": "已暂停",
        "completed": "已完成",
        "failed": "失败",
        "stopped": "已停止",
        "error": "请求错误",
    }.get(str(status), str(status))

    cols = st.columns(4)
    cols[0].metric("状态", "已暂停" if paused and alive else label)
    cols[1].metric("当前数据量", f"{int(snapshot.get('total_items') or 0):,}")
    cols[2].metric("本轮新增", f"{int(snapshot.get('written_items') or 0):,}")
    cols[3].metric("跳过重复", f"{int(snapshot.get('skipped_duplicates') or 0):,}")

    if message := snapshot.get("message"):
        st.caption(str(message))
    if error := snapshot.get("error"):
        st.error(str(error), icon=":material/error:")
    if next_id := snapshot.get("next_id"):
        st.caption(f"断点 nextId: `{next_id}`")


def render_crawler_logs(runtime: CrawlerRuntime) -> None:
    logs = runtime.snapshot().get("logs") or []
    with st.expander("运行日志", icon=":material/terminal:", expanded=False):
        if logs:
            log_text = "\n".join(logs)
            LOG_VIEWER(
                data={"text": log_text},
                key="crawler_log_viewer",
                height=320,
            )
            st.download_button(
                "下载日志",
                data=log_text.encode("utf-8"),
                file_name="bmall_crawler.log",
                mime="text/plain",
                icon=":material/download:",
            )
        else:
            st.caption("暂无日志。启动爬虫后会在这里显示请求、错误和完成状态。")


def build_crawler_config() -> CrawlerConfig | None:
    st.session_state.setdefault("crawler_cookie_header", os.environ.get("BMALL_COOKIE", ""))
    checkpoint_config = read_crawl_state(ROOT / "Data").get("config") or {}
    sort_defaults = labels_for_option_names(
        SORT_TYPE_LABELS,
        checkpoint_config.get("sort_types"),
    ) or [SORT_TYPE_LABELS[SortType.PRICE_DESC]]
    price_defaults = labels_for_option_names(
        PRICE_FILTER_LABELS,
        checkpoint_config.get("price_filters"),
    ) or enum_labels(PRICE_FILTER_LABELS)
    discount_defaults = labels_for_option_names(
        DISCOUNT_FILTER_LABELS,
        checkpoint_config.get("discount_filters"),
    ) or enum_labels(DISCOUNT_FILTER_LABELS)

    with st.container(border=True):
        st.subheader("抓取范围", anchor=False)
        st.caption(
            "用于组合接口请求。排序类型会按选择顺序依次扫描；价格和折扣过滤默认全选，取消某些区间可以减少请求范围。"
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            sort_types = render_enum_pills(
                "排序类型",
                SORT_TYPE_LABELS,
                "crawler_sort",
                sort_defaults,
            )
        with col2:
            price_filters = render_enum_pills(
                "价格过滤",
                PRICE_FILTER_LABELS,
                "crawler_price",
                price_defaults,
            )
        with col3:
            discount_filters = render_enum_pills(
                "折扣过滤",
                DISCOUNT_FILTER_LABELS,
                "crawler_discount",
                discount_defaults,
            )

        if not sort_types or not price_filters:
            st.warning("至少选择 1 个排序类型和 1 个价格过滤。", icon=":material/warning:")
            return None
        st.caption(
            "每组选择 1 个按钮时按单一条件抓取；选择多个按钮时自动按多条件组合抓取。"
        )

    with st.container(border=True):
        st.subheader("连接设置", anchor=False)
        st.caption(
            "Cookie 用于让接口识别你的登录态。可以打开会员购市集页面后，从浏览器开发者工具的请求头里复制 Cookie。"
        )
        uploaded_cookie = st.file_uploader(
            "导入 cookie 文件",
            type=["txt"],
            help="上传只包含一行 Cookie 请求头的 .txt 文件。文件内容只保存在当前浏览器会话中。",
        )
        if uploaded_cookie is not None:
            st.session_state["crawler_cookie_header"] = (
                uploaded_cookie.getvalue().decode("utf-8", errors="ignore").strip()
            )
        cookie_header = st.text_input(
            "Cookie",
            key="crawler_cookie_header",
            type="password",
            placeholder="SESSDATA=...; bili_jct=...; DedeUserID=...",
            help=(
                "从 https://mall.bilibili.com/neul-next/index.html?page=magic-market_index "
                "这个页面对应请求的请求头里复制 Cookie。不会写入代码，也不会在页面上明文展示。"
            ),
        )
        st.caption(
            "获取入口：https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
        )
        if not cookie_header.strip():
            st.warning("未提供 Cookie，接口可能无法返回完整数据。", icon=":material/warning:")

        env_proxy = detect_env_proxy()
        default_proxy_mode = "使用环境变量" if env_proxy else "关闭"
        proxy_mode = st.segmented_control(
            "代理",
            ["关闭", "使用环境变量", "手动输入"],
            default=default_proxy_mode,
            key="crawler_proxy_mode",
            help=(
                "- 关闭：不显式设置代理，也不读取环境变量。\n"
                "- 使用环境变量：读取 HTTPS_PROXY、HTTP_PROXY 或 ALL_PROXY。\n"
                "- 手动输入：只使用下方填写的代理地址。"
            ),
        )
        proxy = None
        trust_env = False
        if proxy_mode == "使用环境变量":
            trust_env = True
            if env_proxy:
                st.caption(f"已识别环境变量代理：`{env_proxy}`")
            else:
                st.warning("未识别到本机代理环境变量。", icon=":material/warning:")
        elif proxy_mode == "手动输入":
            proxy = st.text_input(
                "代理地址",
                placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890",
                key="crawler_manual_proxy",
            ).strip() or None

    with st.container(border=True):
        st.subheader("运行参数", anchor=False)
        st.caption("控制请求节奏、错误容忍度和写入策略。请求间隔过低容易触发平台限流。")
        sleep_range = st.slider(
            "每次请求间隔",
            min_value=1.25,
            max_value=5.0,
            value=(1.25, 1.5),
            step=0.05,
            format="%.2f 秒",
            help="建议保持默认值，过快容易触发平台限流。",
        )
        max_retries = st.number_input(
            "连续失败终止阈值",
            min_value=1,
            max_value=100,
            value=10,
            step=1,
            help=(
                "连续请求失败达到这个次数后自动停止爬虫。网络不稳定时可以调高；"
                "如果频繁遇到 412/429，建议保持较低并暂停一段时间。"
            ),
        )
        dedupe_output = st.toggle(
            "写入时跳过重复商品",
            value=True,
            help=(
                "按 c2cItemsId 过滤已经保存过的商品。\n"
                "- 开启：适合重新扫描新数据、保留历史数据并追加新增商品。\n"
                "- 关闭：保留接口原始返回，可能写入重复商品，通常只用于调试。"
            ),
        )

    return CrawlerConfig(
        sort_types=tuple(sort_types),
        price_filters=tuple(price_filters),
        discount_filters=tuple(discount_filters),
        cookie_header=cookie_header,
        data_dir=ROOT / "Data",
        proxy=proxy,
        trust_env=trust_env,
        sleep_range=tuple(sleep_range),
        max_retries=int(max_retries),
        dedupe_output=dedupe_output,
    )


def render_crawler_runner() -> None:
    st.markdown(
        """
        <div class="mall-header">
            <div class="mall-kicker">Crawler control</div>
            <h1 class="mall-title">交互式爬虫运行</h1>
            <div class="mall-subtitle">
                选择排序、价格和折扣范围，导入自己的 Cookie，并在运行过程中暂停、继续或从头重跑。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    runtime = get_crawler_runtime()
    render_crawler_status(runtime)
    render_crawler_logs(runtime)
    config = build_crawler_config()
    snapshot = runtime.snapshot()
    is_alive = snapshot["alive"]
    is_paused = snapshot["paused"]

    with st.container(border=True):
        st.subheader("运行控制", anchor=False)
        st.caption(
            "开始/继续断点会复用磁盘断点；重新扫描新数据会保留 jsonl 并从第一页去重追加；清除现有数据会删除 jsonl 和断点。"
        )
        with st.container(horizontal=True, horizontal_alignment="left"):
            start_clicked = st.button(
                "开始 / 继续断点",
                icon=":material/play_arrow:",
                type="primary",
                disabled=is_alive or config is None,
                key="crawler_action_start",
            )
            reset_clicked = st.button(
                "重新扫描新数据",
                icon=":material/refresh:",
                disabled=is_alive or config is None,
                help="清除断点但保留现有 jsonl，从第一页重新扫描，并把新商品去重追加到现有数据。",
                key="crawler_action_reset",
            )
            clear_clicked = st.button(
                "清除现有数据",
                icon=":material/delete:",
                disabled=is_alive,
                help="删除现有 jsonl 和断点。之后点击开始会从零开始抓取。",
                key="crawler_action_clear_data",
            )
            pause_clicked = st.button(
                "暂停",
                icon=":material/pause:",
                disabled=not is_alive or is_paused,
                key="crawler_action_pause",
            )
            resume_clicked = st.button(
                "继续",
                icon=":material/play_arrow:",
                disabled=not is_alive or not is_paused,
                key="crawler_action_resume",
            )
            stop_clicked = st.button(
                "停止",
                icon=":material/stop:",
                disabled=not is_alive,
                key="crawler_action_stop",
            )

    if start_clicked and config is not None:
        start_crawler(config, reset=False)
        st.toast("爬虫已启动", icon=":material/play_arrow:")
        st.rerun()
    if reset_clicked and config is not None:
        load_items.clear()
        start_crawler(config, restart=True)
        st.toast("已从第一页重新扫描，现有数据会保留并去重追加", icon=":material/refresh:")
        st.rerun()
    if clear_clicked:
        clear_existing_crawl_data()
        st.toast("已清除现有数据和断点", icon=":material/delete:")
        st.rerun()
    if pause_clicked:
        runtime.control.pause()
        runtime.update(status="paused", message="将在当前请求结束后暂停")
        runtime.append_log("INFO 用户请求暂停，当前请求结束后进入暂停状态")
        st.rerun()
    if resume_clicked:
        runtime.control.resume()
        runtime.update(status="running", message="爬虫已继续运行")
        runtime.append_log("INFO 用户请求继续运行")
        st.rerun()
    if stop_clicked:
        runtime.control.stop()
        runtime.update(status="stopped", message="正在停止爬虫")
        runtime.append_log("INFO 用户请求停止爬虫")
        st.rerun()

    if is_alive:
        time.sleep(1)
        st.rerun()


def render_header() -> None:
    """Render the product-facing app header without storage or runtime details."""
    st.markdown(
        """
        <div class="mall-header">
            <div class="mall-kicker">Bilibili mall finder</div>
            <h1 class="mall-title">商品预览与低价检索</h1>
            <div class="mall-subtitle">
                快速筛选会员购市集商品，按价格、折扣和库存排序，找到合适商品后直接跳转购买页面。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_cards(results: pd.DataFrame) -> None:
    for _, row in results.iterrows():
        with st.container(border=True):
            image_col, info_col, action_col = st.columns(
                [0.85, 3.8, 1.25],
                vertical_alignment="center",
            )

            with image_col:
                if row.get("imageUrl"):
                    image_url = html.escape(str(row["imageUrl"]), quote=True)
                    st.markdown(
                        (
                            '<div class="thumb-frame">'
                            f'<img src="{image_url}" alt="" referrerpolicy="no-referrer">'
                            "</div>"
                        ),
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="thumb-frame"><span class="thumb-empty">No image</span></div>',
                        unsafe_allow_html=True,
                    )

            with info_col:
                name = html.escape(str(row.get("c2cItemsName", "")))
                detail = html.escape(str(row.get("detailName") or ""))
                seller = html.escape(str(row.get("uname") or "-"))
                st.markdown(f'<p class="result-title">{name}</p>', unsafe_allow_html=True)
                if detail and detail != name:
                    st.markdown(
                        f'<p class="result-detail">{detail}</p>',
                        unsafe_allow_html=True,
                    )
                st.markdown(
                    (
                        f'<div class="meta-line">卖家 {seller} · '
                        f'库存 {int(row.get("totalItemsCount", 0))} · '
                        f'商品 ID {row.get("c2cItemsId")}</div>'
                    ),
                    unsafe_allow_html=True,
                )

            with action_col:
                st.markdown(
                    f'<div class="price">{_format_yuan(row.get("priceYuan"))}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="market">市场价 {_format_yuan(row.get("marketYuan"))}</div>',
                    unsafe_allow_html=True,
                )
                discount = row.get("discountPct")
                badges = []
                if pd.notna(discount):
                    badges.append(f'<span class="soft-badge pink-badge">省 {discount:.0f}%</span>')
                if int(row.get("totalItemsCount", 0)) == 1:
                    badges.append('<span class="soft-badge">单件</span>')
                elif int(row.get("totalItemsCount", 0)) > 1:
                    badges.append(
                        f'<span class="soft-badge">多件 x{int(row["totalItemsCount"])}</span>'
                    )
                if int(row.get("titleDuplicateCount", 1)) > 1:
                    badges.append(
                        f'<span class="soft-badge">重复 {int(row["titleDuplicateCount"])} 条</span>'
                    )
                if badges:
                    st.markdown(
                        f'<div class="badge-row">{"".join(badges)}</div>',
                        unsafe_allow_html=True,
                    )
                st.link_button(
                    "打开商品",
                    row["c2cItemsLink"],
                    icon=":material/open_in_new:",
                    use_container_width=True,
                )


def render_table(results: pd.DataFrame) -> None:
    table = results[
        [
            "imageUrl",
            "c2cItemsName",
            "priceYuan",
            "marketYuan",
            "discountPct",
            "totalItemsCount",
            "titleDuplicateCount",
            "uname",
            "c2cItemsLink",
        ]
    ].rename(
        columns={
            "imageUrl": "缩略图",
            "c2cItemsName": "商品名称",
            "priceYuan": "价格",
            "marketYuan": "市场价",
            "discountPct": "优惠比例",
            "totalItemsCount": "库存",
            "titleDuplicateCount": "重复数",
            "uname": "卖家",
            "c2cItemsLink": "链接",
        }
    )
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        height=min(720, 84 + len(table) * 72),
        column_config={
            "缩略图": st.column_config.ImageColumn(width="small"),
            "商品名称": st.column_config.TextColumn(width="large", pinned=True),
            "价格": st.column_config.NumberColumn(format="¥%.2f"),
            "市场价": st.column_config.NumberColumn(format="¥%.2f"),
            "优惠比例": st.column_config.NumberColumn(format="%.0f%%"),
            "链接": st.column_config.LinkColumn(display_text="打开"),
        },
    )


with st.expander("运行爬虫", icon=":material/play_arrow:", expanded=False):
    render_crawler_runner()

render_header()

with st.spinner("正在读取商品数据..."):
    if DATA_PATH.exists():
        mtime_ns, size = _file_signature(DATA_PATH)
        data = load_items(str(DATA_PATH), mtime_ns, size, DATA_SCHEMA_VERSION)
    elif data_url := configured_data_url():
        data = load_items_from_url(data_url, DATA_SCHEMA_VERSION)
    else:
        st.error(
            "未找到商品数据。请在本地提供 Data/bmall_all_data.jsonl，或在部署环境配置 BMALL_DATA_URL。",
            icon=":material/error:",
        )
        st.stop()

if data.empty:
    st.warning("数据文件为空。", icon=":material/warning:")
    st.stop()

price_min = math.floor(data["priceYuan"].min())
price_max = math.ceil(data["priceYuan"].max())
price_bounds = slider_bounds(price_min, price_max)

with st.sidebar:
    st.header("筛选", divider=False)
    with st.form("filters", border=False):
        query = st.text_input(
            "商品关键词",
            placeholder="例如：诗歌剧、晓美焰、手办",
            help=(
                "会在商品标题、首个明细商品名称和卖家名里搜索。\n\n"
                "- 输入多个词时用空格分隔，例如：`晓美焰 手办`。\n"
                "- 商品标题是列表里看到的整条市集商品名称。\n"
                "- 首个明细商品是 `detailDtoList` 里的第一件具体物品。例如一个“等 10 个商品”的套装，标题可能是套装标题，首个明细商品可能是其中第一件手办。"
            ),
        )
        search_mode = st.segmented_control(
            "关键词匹配",
            ["全部关键词", "任一关键词"],
            default="全部关键词",
            help=(
                "- 全部关键词：每个词都要命中。例如输入 `晓美焰 手办`，结果必须同时包含“晓美焰”和“手办”。\n"
                "- 任一关键词：命中其中一个词即可。例如输入 `晓美焰 鹿目圆`，包含“晓美焰”或“鹿目圆”的商品都会出现。"
            ),
        )
        if price_bounds is None:
            price_range = (price_min, price_max)
            st.caption(f"当前数据只有一个价格档位：¥{price_min:,}")
        else:
            price_range = st.slider(
                "价格区间",
                min_value=price_bounds[0],
                max_value=price_bounds[1],
                value=price_bounds,
                format="¥%d",
                help="按商品出售价格筛选，单位是元。",
            )
        sort_mode = st.selectbox(
            "排序",
            ["价格从低到高", "折扣力度优先", "库存数量优先", "最新抓取优先"],
            help=(
                "- 价格从低到高：售价最低的商品排在最前。\n"
                "- 折扣力度优先：优惠比例最高的商品排在最前，优惠比例 = 1 - 售价 / 市场价。\n"
                "- 库存数量优先：一个市集商品中包含物品更多的排在更前。\n"
                "- 最新抓取优先：按数据文件中越靠后的记录排在越前，通常表示越晚抓到。"
            ),
        )
        quantity_mode = st.segmented_control(
            "商品数量",
            ["全部", "单件", "多件"],
            default="全部",
            help=(
                "- 全部：不按数量过滤。\n"
                "- 单件：只看 `totalItemsCount = 1` 的商品。\n"
                "- 多件：只看 `totalItemsCount > 1` 的商品，例如标题里常见的“等 N 个商品”。"
            ),
        )
        product_type = st.segmented_control(
            "商品类型",
            ["全部", "普通商品", "福袋"],
            default="全部",
            help=(
                "- 全部：不按类型过滤。\n"
                "- 普通商品：接口 `type = 1`。\n"
                "- 福袋：接口 `type = 2`，商品明细可能被隐藏或使用占位信息。"
            ),
        )
        with_image = st.toggle(
            "只看有缩略图",
            value=True,
            help="开启后过滤掉没有可展示图片链接的商品。",
        )
        hidden_mode = st.selectbox(
            "隐藏信息",
            ["全部", "排除隐藏信息", "只看隐藏信息"],
            help=(
                "- 全部：不过滤隐藏明细。\n"
                "- 排除隐藏信息：过滤掉明细里 `isHidden = true` 的商品，适合只看名称和图片明确的商品。\n"
                "- 只看隐藏信息：只看明细被隐藏的商品，常见于福袋或占位商品。"
            ),
        )
        min_discount = st.slider(
            "最低优惠比例",
            0,
            90,
            0,
            format="%d%%",
            help="优惠比例 = 1 - 售价 / 市场价。市场价缺失或为 0 的商品不会命中这个条件。",
        )
        duplicate_mode = st.selectbox(
            "重复商品",
            ["不过滤重复", "每个商品只保留最低价", "每个商品保留最低 N 个"],
            index=1,
            help=(
                "- 不过滤重复：保留所有记录。\n"
                "- 每个商品只保留最低价：同一组重复商品里，只保留售价最低的一条。\n"
                "- 每个商品保留最低 N 个：同一组重复商品里，保留售价最低的 N 条，用于比较多个低价卖家。"
            ),
        )
        duplicate_key_mode = st.segmented_control(
            "重复判断",
            ["按商品标题", "按首个明细商品"],
            default="按商品标题",
            help=(
                "- 按商品标题：标题完全一致才算重复。例：两条都叫 `GSC 晓美焰 手办` 才归为同一组。\n"
                "- 按首个明细商品：用 `detailDtoList` 里的第一件具体物品判断重复。例：两个套装标题不同，但第一件明细都是 `GSC 晓美焰 手办`，会归为同一组。\n"
                "- 如果是福袋或隐藏商品，首个明细可能为空或是占位信息，这时建议优先用“按商品标题”。"
            ),
        )
        duplicate_keep_n = st.slider(
            "每组保留数量",
            1,
            10,
            3,
            help="仅在“每个商品保留最低 N 个”时生效。",
        )
        submitted = st.form_submit_button(
            "查询",
            icon=":material/search:",
            type="primary",
            use_container_width=True,
        )
        if submitted:
            st.session_state["result_page"] = 1

base_filtered = filter_items(
    data,
    query=query,
    price_range=price_range,
    quantity_mode=quantity_mode,
    product_type=product_type,
    hidden_mode=hidden_mode,
    search_mode=search_mode,
    with_image=with_image,
    min_discount=min_discount,
)
deduped = reduce_duplicates(
    base_filtered,
    duplicate_mode=duplicate_mode,
    duplicate_key_mode=duplicate_key_mode,
    duplicate_keep_n=duplicate_keep_n,
)
filtered = sort_items(deduped, sort_mode)

metric_cols = st.columns(4)
metric_cols[0].metric("数据量", f"{len(data):,}")
metric_cols[1].metric("筛选命中", f"{len(base_filtered):,}")
metric_cols[2].metric("当前结果", f"{len(filtered):,}")
metric_cols[3].metric(
    "最低价",
    _format_yuan(filtered["priceYuan"].min()) if not filtered.empty else "¥-",
)

left, middle, right = st.columns([1, 1, 1.25], vertical_alignment="center")
with left:
    view = st.segmented_control(
        "展示方式",
        ["商品卡片", "数据表格"],
        default="商品卡片",
        label_visibility="collapsed",
        help="商品卡片适合浏览图片和价格；数据表格适合排序、复制和快速扫描字段。",
    )
with middle:
    page_size = st.selectbox(
        "每页显示",
        [24, 48, 96, 192, 500, 1000],
        index=1,
        help="控制当前页一次渲染多少条。数值越大，页面越长，浏览器渲染也会更重。",
    )
with right:
    csv_data = filtered[
        [
            "c2cItemsName",
            "priceYuan",
            "marketYuan",
            "discountPct",
            "totalItemsCount",
            "titleDuplicateCount",
            "uname",
            "c2cItemsLink",
        ]
    ].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "导出当前结果",
        data=csv_data,
        file_name="bmall_search_results.csv",
        mime="text/csv",
        icon=":material/download:",
        use_container_width=True,
        help="导出当前筛选、去重和排序后的全部结果，不只导出当前页。",
    )

if filtered.empty:
    st.info("没有匹配结果，可以放宽关键词、价格区间或优惠比例。", icon=":material/info:")
else:
    page_count = max(1, math.ceil(len(filtered) / page_size))
    if "result_page" not in st.session_state:
        st.session_state["result_page"] = 1
    if st.session_state["result_page"] > page_count:
        st.session_state["result_page"] = page_count

    page_col, caption_col = st.columns([1, 3], vertical_alignment="center")
    with page_col:
        page = st.number_input(
            "页码",
            min_value=1,
            max_value=page_count,
            step=1,
            key="result_page",
            help="跳转到指定页。每页条数由上方“每页显示”控制。",
        )
    start_index = (page - 1) * page_size + 1
    end_index = min(page * page_size, len(filtered))
    with caption_col:
        st.caption(f"第 {start_index:,}-{end_index:,} 条 / 共 {len(filtered):,} 条")

    page_results = paginate(filtered, page, page_size)
    if view == "数据表格":
        render_table(page_results)
    else:
        render_cards(page_results)
