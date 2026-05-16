from enum import Enum


class SortType(Enum):
    """
    排序类型
    """

    TIME_DESC = "TIME_DESC"  # 综合（默认时间降序）
    PRICE_DESC = "PRICE_DESC"  # 价格倒序
    PRICE_ASC = "PRICE_ASC"  # 价格升序


class PieceFilters(Enum):
    """
    价格过滤类型
    """

    BELOW_TWENTY = ["0-2000"]  # 20 以下
    TWENTY2THIRTY = ["2000-3000"]  # 20 - 30
    THIRTY2FIFTY = ["3000-5000"]  # 30 - 50
    FIFTY2HUNDRED = ["5000-10000"]  # 50 - 100
    HUNDRED2TWO_HUNDRED = ["10000-20000"]  # 100 - 200
    OVER_TWO_HUNDRED = ["20000-0"]  # 200 以上


class DiscountFilters(Enum):
    """
    折扣过滤类型
    """

    BELOW_THIRTY = ["0-30"]  # 3 折以下
    THIRTY2FIFTY = ["30-50"]  # 3 - 5 折
    FIFTY2SEVENTY = ["50-70"]  # 5 - 7 折
    OVER_SEVENTY = ["70-100"]  # 7 折以上


SORT_TYPE_LABELS = {
    SortType.TIME_DESC: "综合",
    SortType.PRICE_DESC: "价格从高到低",
    SortType.PRICE_ASC: "价格从低到高",
}

PRICE_FILTER_LABELS = {
    PieceFilters.BELOW_TWENTY: "20 元以下",
    PieceFilters.TWENTY2THIRTY: "20 - 30 元",
    PieceFilters.THIRTY2FIFTY: "30 - 50 元",
    PieceFilters.FIFTY2HUNDRED: "50 - 100 元",
    PieceFilters.HUNDRED2TWO_HUNDRED: "100 - 200 元",
    PieceFilters.OVER_TWO_HUNDRED: "200 元以上",
}

DISCOUNT_FILTER_LABELS = {
    DiscountFilters.BELOW_THIRTY: "3 折以下",
    DiscountFilters.THIRTY2FIFTY: "3 - 5 折",
    DiscountFilters.FIFTY2SEVENTY: "5 - 7 折",
    DiscountFilters.OVER_SEVENTY: "7 折以上",
}

ENV_PROXY_KEYS = (
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "ALL_PROXY",
    "all_proxy",
)
