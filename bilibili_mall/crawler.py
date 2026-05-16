import asyncio
import os

import aiofiles
import numpy as np
import orjson
import pandas as pd
from aiofiles import os as aioos
from aiofiles import tempfile as aiotempfile
from curl_cffi import AsyncSession, Cookies, Headers, Request, Response
from curl_cffi.requests.exceptions import HTTPError

from .crawler_options import DiscountFilters, PieceFilters, SortType
from .utils import logger


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
        # 总元数据计数
        total_items = 0

        # 最大重试次数
        MAX_RETRIES = 10
        # 错误命中计数
        HIT_COUNTS = 0

        # 存储路径
        save_id_path = "./Data/bmall_next_id.txt"
        save_data_path = "./Data/bmall_all_data.jsonl"
        await aioos.makedirs(os.path.dirname(save_id_path), exist_ok=True)
        await aioos.makedirs(os.path.dirname(save_data_path), exist_ok=True)

        #!断点续传
        if await aioos.path.exists(save_id_path):
            async with aiofiles.open(save_id_path, "r", encoding="utf-8") as f:
                next_id = (await f.read()).strip() or None
                if next_id == "None":
                    next_id = None
        if await aioos.path.exists(save_data_path):
            async with aiofiles.open(save_data_path, "rb") as f:
                async for _ in f:
                    total_items += 1

        url = "https://mall.bilibili.com/mall-magic-c/internet/c2c/v2/list"
        referer = (
            "https://mall.bilibili.com/neul-next/index.html?page=magic-market_index"
        )
        cookies = "buvid3=88D99652-B810-21E5-1BE9-9586BC2F74B272541infoc; b_nut=1764390371; _uuid=B93AAC10D-10310C-45D3-77103-FF9F1102E1E8D72933infoc; buvid_fp=55db4bfa14c4dcfe75360378c70c7566; rpdid=|(um~lRmmkl~0J'u~YRJm|J~R; SESSDATA=7f5e4839%2C1779942453%2C66d7a%2Ab1CjCorxDTQPXv62bRZKE4QAxGx1K7wUON60N-YBg2j3bZCJTgP86U68yMBJVpJduyOCcSVjYwX0hDSEpPZU1jMHE1RWFSYVl1RWhucEQtTFpTZ25BSXNrZmhyb1VGcXE3NU5TVm50RWZ6RnUyUUJPa0NYS0MtTlY5WnFhWmRqOGhWa2ttN2xlSXFBIIEC; bili_jct=a976cb1a7f5ccd5cf584eb64f7a05eb8; DedeUserID=86137069; DedeUserID__ckMd5=9c9e29b3c177de79; sid=5jl3ee0l; theme-tip-show=SHOWED; LIVE_BUVID=AUTO8517688974973005; Hm_lvt_8d8d2f308d6e6dffaf586bd024670861=1772205538,1774199136; buvid4=A55F8A7D-608B-CAD1-BDAE-CC39A6EBC40G78922-026050119-RjFYgDsx4sGH6nuVnLhNGw%3D%3D; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3Nzg1ODgwNjcsImlhdCI6MTc3ODMyODgwNywicGx0IjotMX0.9ybaABpk3rwbGLbSIQ_dA-IoqOhI5TzkiB8QtkMzDbU; bili_ticket_expires=1778588007; home_feed_column=5; CURRENT_FNVAL=4048; ogv_device_support_hdr=1; ogv_device_support_dolby=0; CURRENT_QUALITY=125; bp_t_offset_86137069=1200470950120783875; browser_resolution=1504-406; deviceFingerprint=4dfb2b0af9ce198aff98b8a172ddb3c6; from=pc_mall; b_lsid=50A3F910_19E118D6D02"
        cookies = dict(item.split("=", 1) for item in cookies.split("; "))

        json_data = {
            "nextId": next_id,
            "sortType": SortType.PRICE_DESC.value,
            "priceFilters": (
                PieceFilters.BELOW_TWENTY.value
                + PieceFilters.TWENTY2THIRTY.value
                + PieceFilters.THIRTY2FIFTY.value
                + PieceFilters.FIFTY2HUNDRED.value
                + PieceFilters.HUNDRED2TWO_HUNDRED.value
                + PieceFilters.OVER_TWO_HUNDRED.value
            ),
            "discountFilters": None,
        }

        while True:
            try:
                #!经过测试，每次的间隔必须大于 1.25s（每分钟不超过大约 50 次请求），否则引起服务器 412 错误：{"code":-412,"message":"request was banned","ttl":1}
                await asyncio.sleep(
                    np.random.uniform(1.25, 1.3),
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

                async with aiofiles.open(save_data_path, "ab") as f:
                    await f.write(b"".join(orjson.dumps(item) + b"\n" for item in data))

                total_items += len(data)
                logger.info(f"Fetched {len(data)} items, total {total_items} items")

                async with aiofiles.open(save_id_path, "w", encoding="utf-8") as f:
                    await f.write(f"{next_id}")

                # 市集返回的数据是一个环形列表，因此不加以阻断会无限爬取重复的数据，故需要在发现重复的 nextId 时停止爬取（初始 next_id 永远为 None）
                if next_id is None:
                    logger.info(f"All data fetched, total {total_items} items")
                    break

                json_data["nextId"] = next_id

            except Exception as exc:
                logger.error(f"{exc.__class__.__name__} - {exc}")
                await asyncio.sleep(
                    np.random.uniform(0.2, 0.3),
                )

                # HTTP 请求错误，累计错误命中计数
                HIT_COUNTS += 1
                # 当大于最大重试次数时，停止抓取（此时很有可能已经被平台封禁），而小于最大重试次数时，继续抓取（有可能是网络问题，或者只是短暂的刷屏速度过快，服务器并未封禁账号）
                if HIT_COUNTS >= MAX_RETRIES:
                    logger.critical("Too many http errors, stop fetching")
                    break
                else:
                    continue
