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
            proxy="127.0.0.1:7897",
            trust_env=True,
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
        cookies = "CURRENT_QUALITY=125;b_lsid=4A9838B5_19C4BC6E3CA;Hm_lpvt_8d8d2f308d6e6dffaf586bd024670861=1769855660;theme-tip-show=SHOWED;home_feed_column=5;LIVE_BUVID=AUTO8517688974973005;buvid4=1BB1BC11-DC29-B5AF-573D-8D287EF74FAG52669-026013017-fGzWhFBjsdBah6PdANDPTPPnNX1sL1rFLtcDlOXOmQyOvJKqzZxLwTA01CPOPqfs;CURRENT_FNVAL=2000;buvid3=88D99652-B810-21E5-1BE9-9586BC2F74B272541infoc;kfcFrom=market_detail;sid=5jl3ee0l;SESSDATA=7f5e4839%2C1779942453%2C66d7a%2Ab1CjCorxDTQPXv62bRZKE4QAxGx1K7wUON60N-YBg2j3bZCJTgP86U68yMBJVpJduyOCcSVjYwX0hDSEpPZU1jMHE1RWFSYVl1RWhucEQtTFpTZ25BSXNrZmhyb1VGcXE3NU5TVm50RWZ6RnUyUUJPa0NYS0MtTlY5WnFhWmRqOGhWa2ttN2xlSXFBIIEC;bsource=search_bing;bp_t_offset_86137069=1168049182596923430;deviceFingerprint=88473ae963b10f2382d65e7c7924bfd1;b_nut=1764390371;_uuid=B93AAC10D-10310C-45D3-77103-FF9F1102E1E8D72933infoc;bili_jct=a976cb1a7f5ccd5cf584eb64f7a05eb8;bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NzA5MTQ2OTcsImlhdCI6MTc3MDY1NTQzNywicGx0IjotMX0.zwAPb6kL9r6X-FJa4-hVvx1lMw3JdQz0Xwqx8htcOqw;bili_ticket_expires=1770914637;browser_resolution=1504-863;buvid_fp=55db4bfa14c4dcfe75360378c70c7566;DedeUserID=86137069;DedeUserID__ckMd5=9c9e29b3c177de79;Hm_lvt_8d8d2f308d6e6dffaf586bd024670861=1769855436;HMACCOUNT=74F41F67F4E068AC;rpdid=|(um~lRmmkl~0J'u~YRJm|J~R"
        cookies = dict(item.split("=", 1) for item in cookies.split("; "))

        json_data = {
            "nextId": next_id,
            "sortType": SortType.PIECE_DESC.value,
            "priceFilters": (
                PieceFilters.BELOW_TWENTY.value
                + PieceFilters.TWENTY2THIRTY.value
                + PieceFilters.THIRTY2FIFTY.value
                + PieceFilters.FIFTY2HUNDRED.value
                + PieceFilters.HUNDRED2TWO_HUNDRED.value
                + PieceFilters.OVER_TWO_HUNDRED.value,
            ),
            "discountFilters": None,
        }

        while True:
            try:
                #!经过测试，每次的间隔必须大于 1.2s（每分钟不超过大约 50 次请求），否则引起服务器 412 错误：{"code":-412,"message":"request was banned","ttl":1}
                await asyncio.sleep(
                    np.random.uniform(1.2, 1.5),
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
