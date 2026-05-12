from __future__ import annotations

import html
import math
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "Data" / "bmall_all_data.jsonl"
DATA_SCHEMA_VERSION = 2
DETAIL_URL = (
    "https://mall.bilibili.com/neul-next/index.html"
    "?page=magic-market_detail&noTitleBar=1&itemsId={items_id}&from=market_index"
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
    return _prepare_items(pd.read_json(path, lines=True))


@st.cache_data(show_spinner=False, max_entries=3, ttl="10m")
def load_items_from_url(url: str, schema_version: int) -> pd.DataFrame:
    _ = schema_version
    return _prepare_items(pd.read_json(url, lines=True))


def configured_data_url() -> str:
    return str(
        st.secrets.get("BMALL_DATA_URL") or os.environ.get("BMALL_DATA_URL") or ""
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

price_min = int(data["priceYuan"].min())
price_max = int(data["priceYuan"].max())

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
        price_range = st.slider(
            "价格区间",
            min_value=price_min,
            max_value=price_max,
            value=(price_min, price_max),
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
