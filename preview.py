import asyncio
import re
from playwright.async_api import Playwright, async_playwright, expect
import pandas as pd
import orjson
from spdl.pipeline import PipelineBuilder

save_path = "./Data/bmall_all_data.json"

with open(save_path, "rb") as f:
    content = f.read()
    all_data = orjson.loads(content)

df = pd.DataFrame(all_data)

# f"https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId={c2cItemsId}&from=market_index"
df["c2cItemsLink"] = df["c2cItemsId"].apply(
    lambda x: f"https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId={x}&from=market_index"
)

keyword = "(?i)诗歌剧"

search: pd.DataFrame = df[df["c2cItemsName"].str.contains(keyword, case=False)][
    df["totalItemsCount"] == 1
].drop_duplicates(
    subset=["c2cItemsName"],
    keep="last",
)
print(len(search))

async def run(playwright: Playwright) -> None:
    device = playwright.devices["iPhone 15 Pro Max"]
    browser = await playwright.chromium.launch(
        headless=False,
        # devtools=False,
    )
    context = await browser.new_context(**device)
    for index, row in search.iterrows():
        page = await context.new_page()
        await page.goto(
            row["c2cItemsLink"],
            # wait_until="networkidle",
        )

    # 等待所有页面被用户手动关闭
    while pages := context.pages:
        if len(pages) == 0:
            break
        await asyncio.sleep(1)  # 每秒检查一次

    await context.close()
    await browser.close()


async def main() -> None:
    async with async_playwright() as playwright:
        await run(playwright)


asyncio.run(main())
