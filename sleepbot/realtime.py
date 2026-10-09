"""リアルタイム共有: 「リアルタイムでも共有する」を選んだ人の就寝・起床を REPORT_CHANNEL_ID に投稿する。

投稿してよいかは visible_fields() の Field.REALTIME だけで決める。手入力（/edit）は投稿しない。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import discord

from sleepbot.config import JST
from sleepbot.db import User
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.safelog import log, log_exception
from sleepbot.sleeplog import format_duration
from sleepbot.weekly import safe_name

if TYPE_CHECKING:
    from sleepbot.bot import SleepBot


def _clock(dt: datetime) -> str:
    local = dt.astimezone(JST)
    return f"{local.hour}:{local.minute:02d}"


def sleep_message(user: User, name: str, at: datetime) -> str | None:
    if Field.REALTIME not in visible_fields(user, Audience.PUBLIC):
        return None
    return f"😴 **{safe_name(name)}** がおやすみ（{_clock(at)}）"


def wake_message(user: User, name: str, at: datetime, duration_minutes: int, is_nap: bool) -> str | None:
    if Field.REALTIME not in visible_fields(user, Audience.PUBLIC):
        return None
    nap = "・昼寝" if is_nap else ""
    return f"☀️ **{safe_name(name)}** がおきた（{_clock(at)}・{format_duration(duration_minutes)}{nap}）"


async def post(bot: SleepBot, text: str | None) -> None:
    """投稿に失敗してもボタンの処理は止めない。ログに時刻や名前は出さない。"""
    if text is None or bot.cfg.report_channel_id is None:
        return
    try:
        channel = bot.get_channel(bot.cfg.report_channel_id) or await bot.fetch_channel(bot.cfg.report_channel_id)
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        log.warning("realtime report failed")
        log_exception("realtime_post", e)
