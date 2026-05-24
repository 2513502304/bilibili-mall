import logging
import os

from rich.logging import RichHandler


def _build_log_handler() -> logging.Handler:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return logging.StreamHandler()
    return RichHandler(
        level=logging.NOTSET,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        tracebacks_suppress=[],
        tracebacks_max_frames=100,
    )


_LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    if os.environ.get("GITHUB_ACTIONS") == "true"
    else "%(message)s"
)

# 日志记录
logging.basicConfig(
    format=_LOG_FORMAT,
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.WARNING,
    handlers=[_build_log_handler()],
    force=False,
)

logger = logging.getLogger("bilibili-mall")
logger.setLevel(logging.INFO)
