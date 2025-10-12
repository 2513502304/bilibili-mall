import asyncio
import time
from bilibili_mall import BMallSpider
from bilibili_mall.utils import logger

if __name__ == "__main__":
    spider = BMallSpider()
    start = time.time()
    asyncio.run(spider.fetch_all())
    end = time.time()
    logger.info(f"Total time taken: {end - start:.2f} seconds")

# uv run main.py
