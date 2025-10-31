import asyncio
import os
from enum import Enum

import aiofiles
import numpy as np
import orjson
import pandas as pd
from aiofiles import os as aioos
from aiofiles import tempfile as aiotempfile
from curl_cffi import AsyncSession, Cookies, Headers, Request, Response
from curl_cffi.requests.exceptions import HTTPError

from .utils import logger


class SortType(Enum):
    """
    排序类型
    """

    TIME_DESC = "TIME_DESC"  # 综合（默认时间降序）
    PIECE_DESC = "PRICE_DESC"  # 价格倒序
    PIECE_ASC = "PRICE_ASC"  # 价格升序


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


class BMallSpider:
    def __init__(self):
        self.session = AsyncSession(
            max_clients=12,
            base_url=None,
            timeout=30,
            allow_redirects=True,
            impersonate="chrome",
            default_headers=True,
            default_encoding="utf-8",
        )

    async def fetch_all(self):
        # next_id
        next_id: str | None = None
        # 总元数据列表
        all_data: list[dict] = []

        # 最大重试次数
        MAX_RETRIES = 10
        # 错误命中计数
        HIT_COUNTS = 0

        # 存储路径
        save_id_path = "./Data/bmall_next_id.txt"
        save_data_path = "./Data/bmall_all_data.json"
        await aioos.makedirs(os.path.dirname(save_id_path), exist_ok=True)
        await aioos.makedirs(os.path.dirname(save_data_path), exist_ok=True)

        #!断点续传
        if await aioos.path.exists(save_id_path):
            async with aiofiles.open(save_id_path, "r", encoding="utf-8") as f:
                next_id = await f.read()
        if await aioos.path.exists(save_data_path):
            async with aiofiles.open(save_data_path, "rb") as f:
                all_data = orjson.loads(await f.read())

        url = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
        referer = (
            "https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
        )
        cookies = "buvid3=A02095B2-E489-EA41-4FFF-4F300663C4FC97665infoc; b_nut=1761316697; bsource=search_bing; _uuid=551589C6-5C82-7B4A-51DF-A9853107A5D6D97903infoc; enable_web_push=DISABLE; buvid_fp=735996326964332c57898e8e8b7fde24; bmg_af_switch=1; buvid4=5EE57039-5F71-2586-C339-EFC5EF60AC7298833-025102422-HTLmy/kc4BSO/1W6v6lqL6B72BIH/M4C2Ab+Ns9yU+B6qCXxA70oh2g43V8bsXCw; SESSDATA=e22a7f0a%2C1776869490%2Cf43d7%2Aa2CjD2jl7RWHd467XdnyUb-DNIoO0bF4smWk_hZ8Pq9zJtT_HT_-gI8-u8FVCKCXbxZUASVmpqR2lJUERQbEdtV3poYmlKTnNSU0pSeHJSUnVpME9WQ3piZFdlWlY3b0ZaTW16WUM3WTNlR3gxdjBZRkpFeWpuUnhRZVlIZWdkd1F5QlRObm9yQjhBIIEC; bili_jct=dc73eea1fd19213ac72713c35761f141; DedeUserID=86137069; DedeUserID__ckMd5=9c9e29b3c177de79; theme-tip-show=SHOWED; theme-avatar-tip-show=SHOWED; sid=8ajahu1x; rpdid=|(klRmkYlYYY0J'u~YuJk|lkl; CURRENT_QUALITY=80; LIVE_BUVID=AUTO8117613947869128; timeMachine=0; bmg_src_def_domain=i2.hdslb.com; bp_t_offset_86137069=1129476566638657536; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NjIxNTM3NDAsImlhdCI6MTc2MTg5NDQ4MCwicGx0IjotMX0.pIziIZMVhgkDAReDe5RLVr9ABTcBlQnEW_OQV_6dAv4; bili_ticket_expires=1762153680; CURRENT_FNVAL=4048; PVID=8; home_feed_column=4; b_lsid=A96ADDC8_19A39861489; browser_resolution=830-401"
        cookies = dict(item.split("=", 1) for item in cookies.split("; "))

        json_data = {
            "nextId": next_id,
            "sortType": SortType.PIECE_DESC.value,
            "priceFilters": PieceFilters.BELOW_TWENTY.value
            + PieceFilters.TWENTY2THIRTY.value
            + PieceFilters.THIRTY2FIFTY.value
            + PieceFilters.FIFTY2HUNDRED.value
            + PieceFilters.HUNDRED2TWO_HUNDRED.value
            + PieceFilters.OVER_TWO_HUNDRED.value,
            "discountFilters": None,
        }

        while True:
            try:
                #!经过测试，每次的间隔必须大于 1.2s（每分钟不超过大约 50 次请求），否则引起服务器 412 错误：{"code":-412,"message":"request was banned","ttl":1}
                await asyncio.sleep(
                    np.random.uniform(1.2, 1.225),
                )

                response: Response = await self.session.post(
                    url,
                    json=json_data,
                    referer=referer,
                    cookies=cookies,
                )
                response.raise_for_status()

                # 请求成功，则重置错误计数
                if HIT_COUNTS > 0:
                    HIT_COUNTS = 0

                json_: dict = response.json()
                data: list[dict] = json_["data"]["data"]
                next_id = json_["data"]["nextId"]

                all_data.extend(data)
                logger.info(f"Fetched {len(data)} items, total {len(all_data)} items")

                # 市集返回的数据是一个环形列表，因此不加以阻断会无限爬取重复的数据，故需要在发现重复的 nextId 时停止爬取（初始 next_id 永远为 None）
                if next_id is None:
                    logger.info(f"All data fetched, total {len(all_data)} items")
                    break

            except Exception as exc:
                logger.error(f"{exc.__class__.__name__} - {exc}")
                await asyncio.sleep(
                    np.random.uniform(0.25, 0.5),
                )

                # HTTP 请求错误，累计错误命中计数
                HIT_COUNTS += 1
                # 当大于最大重试次数时，停止抓取（此时很有可能已经被平台封禁），而小于最大重试次数时，继续抓取（有可能是网络问题，或者只是短暂的刷屏速度过快，服务器并未封禁账号）
                if HIT_COUNTS >= MAX_RETRIES:
                    logger.critical("Too many http errors, stop fetching")
                    break
                else:
                    continue

            finally:
                async with aiofiles.open(save_id_path, "w", encoding="utf-8") as f:
                    await f.write(f"{next_id}")
                async with aiofiles.open(save_data_path, "wb") as f:
                    await f.write(orjson.dumps(all_data))

            json_data["nextId"] = next_id
