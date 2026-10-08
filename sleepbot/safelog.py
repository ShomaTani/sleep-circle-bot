"""例外を「どこで何型が起きたか」だけ記録する。

例外メッセージやローカル変数には時刻・入力値が入りうるので出さない。
"""

from __future__ import annotations

import logging
import traceback

log = logging.getLogger("sleepbot")


def log_exception(where: str, exc: BaseException) -> None:
    frames = traceback.extract_tb(exc.__traceback__)
    location = " <- ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}" for f in reversed(frames))
    log.error("error in %s: %s at %s", where, type(exc).__name__, location or "?")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # discord.py 自身のログは警告以上だけにする
    logging.getLogger("discord").setLevel(logging.WARNING)
