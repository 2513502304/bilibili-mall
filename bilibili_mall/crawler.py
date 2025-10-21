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
        cookies = "buvid3=9F2B971D-2AE1-A9BC-2013-3BF2AC57917246810infoc; b_nut=1758249346; _uuid=ADD3577A-EF9A-4E63-D3AC-C874101EE1D6652335infoc; enable_web_push=DISABLE; buvid4=3F37126F-334C-54A6-B7D5-8B7A47190EF949075-025091910-09RanKmP+ITnof2LFEgnQQ%3D%3D; DedeUserID=86137069; DedeUserID__ckMd5=9c9e29b3c177de79; theme-tip-show=SHOWED; theme-avatar-tip-show=SHOWED; rpdid=0zbfAI6DyH|riBXoJ6p|3LX|3w1UZr4p; hit-dyn-v2=1; CURRENT_QUALITY=80; theme-switch-show=SHOWED; home_feed_column=5; browser_resolution=1500-877; Hm_lvt_8d8d2f308d6e6dffaf586bd024670861=1759135426,1759858888; fingerprint=695f6cd339f3bd379db9a1ff759cdc8b; buvid_fp_plain=undefined; buvid_fp=695f6cd339f3bd379db9a1ff759cdc8b; SESSDATA=4f65fa90%2C1775979551%2Cff548%2Aa2CjCHpbd4jaKBlnVVnhGrISTndP_aE5c4ji0Jde_bUfbVcT8S55A0hXNMsFww_fgpzvASVmN6Zmp5Tnlnd2JHLXY0eGNJZjFTbjNrZG9oY1A0UnB6S2ZzZnJLcDdnVExtSEdOMDdET19mSXlPRmRLSGtJUjE0eFkyMm4xOGtYSHhSUHl6NFNnQ2dBIIEC; bili_jct=143365b08750514b6ca1da42ea3ed93a; CURRENT_FNVAL=4048; bp_t_offset_86137069=1123516900073013248"
        cookies = {
            cookie.split("=")[0]: cookie.split("=")[1] for cookie in cookies.split("; ")
        }
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

            # 由 raise_for_status() 函数引发的 HTTPError 异常
            except HTTPError as exc:
                logger.error(f"{exc.__class__.__name__} for {exc.response.url} - {exc}")  # type: ignore
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

            # 其他异常，也用于处理全部数据抓取完毕的情况
            except Exception as exc:
                logger.error(f"{exc.__class__.__name__} - {exc}")
                break

            finally:
                async with aiofiles.open(save_id_path, "w", encoding="utf-8") as f:
                    await f.write(f"{next_id}")
                async with aiofiles.open(save_data_path, "wb") as f:
                    await f.write(orjson.dumps(all_data))

            json_data["nextId"] = next_id
