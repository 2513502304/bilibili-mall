from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import streamlit as st

from .crawler_options import (
    DISCOUNT_FILTER_LABELS,
    PRICE_FILTER_LABELS,
    SORT_TYPE_LABELS,
    SortType,
)
from .interactive_crawler import (
    CrawlerConfig,
    detect_env_proxy,
    read_crawl_state,
)
from .crawler_runtime import (
    CrawlerRuntime,
    clear_existing_crawl_data,
    get_crawler_runtime,
    start_crawler,
)

_LOG_VIEWER = None


def get_log_viewer():
    global _LOG_VIEWER
    if _LOG_VIEWER is not None:
        return _LOG_VIEWER

    _LOG_VIEWER = st.components.v2.component(
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
    return _LOG_VIEWER


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
            log_viewer = get_log_viewer()
            log_viewer(
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


def build_crawler_config(data_dir: Path) -> CrawlerConfig | None:
    st.session_state.setdefault("crawler_cookie_header", os.environ.get("BMALL_COOKIE", ""))
    checkpoint_config = read_crawl_state(data_dir).get("config") or {}
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
        data_dir=data_dir,
        proxy=proxy,
        trust_env=trust_env,
        sleep_range=tuple(sleep_range),
        max_retries=int(max_retries),
        dedupe_output=dedupe_output,
    )


def render_crawler_runner(data_dir: Path, clear_data_cache: Callable[[], None]) -> None:
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
    config = build_crawler_config(data_dir)
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
        clear_data_cache()
        start_crawler(config, restart=True)
        st.toast("已从第一页重新扫描，现有数据会保留并去重追加", icon=":material/refresh:")
        st.rerun()
    if clear_clicked:
        clear_existing_crawl_data(data_dir, clear_data_cache)
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
