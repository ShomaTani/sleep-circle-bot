"""リアルタイム共有: 就寝・起床をその場で投稿する。
- 全体（REPORT_CHANNEL_ID）: 「リアルタイムでも共有する」を選んだ人だけ
- グループ（GROUPS のチャンネル）: そのグループのロールを持つ人（自動で共有）

投稿してよいかは visible_fields() の Field.REALTIME だけで決める。手入力（/edit）は投稿しない。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import discord

from sleepbot.config import JST
from sleepbot.db import User
from sleepbot.groups import member_groups
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.safelog import log, log_exception
from sleepbot.sleeplog import format_duration
from sleepbot.weekly import safe_name

if TYPE_CHECKING:
    from sleepbot.bot import SleepBot


def _clock(dt: datetime) -> str:
    local = dt.astimezone(JST)
    return f"{local.hour}:{local.minute:02d}"


def sleep_message(
    user: User, name: str, at: datetime, audience: Audience = Audience.PUBLIC, in_group: bool = False
) -> str | None:
    if Field.REALTIME not in visible_fields(user, audience, in_group):
        return None
    return f"😴 **{safe_name(name)}** がおやすみ（{_clock(at)}）"


def wake_message(
    user: User,
    name: str,
    at: datetime,
    duration_minutes: int,
    is_nap: bool,
    audience: Audience = Audience.PUBLIC,
    in_group: bool = False,
) -> str | None:
    if Field.REALTIME not in visible_fields(user, audience, in_group):
        return None
    nap = "・昼寝" if is_nap else ""
    return f"☀️ **{safe_name(name)}** がおきた（{_clock(at)}・{format_duration(duration_minutes)}{nap}）"


async def post(bot: SleepBot, text: str | None, channel_id: int | None = None) -> None:
    """投稿に失敗してもボタンの処理は止めない。ログに時刻や名前は出さない。
    channel_id を省くと全体の REPORT_CHANNEL_ID に投稿する。"""
    channel_id = channel_id or bot.cfg.report_channel_id
    if text is None or channel_id is None:
        return
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        log.warning("realtime report failed")
        log_exception("realtime_post", e)


async def announce_sleep(bot: SleepBot, user: User, member: discord.abc.User, at: datetime) -> None:
    name = member.display_name
    await post(bot, sleep_message(user, name, at))
    for g in member_groups(bot.cfg.groups, member):
        await post(bot, sleep_message(user, name, at, Audience.GROUP, in_group=True), g.channel_id)


async def announce_wake(
    bot: SleepBot, user: User, member: discord.abc.User, at: datetime, duration_minutes: int, is_nap: bool
) -> None:
    name = member.display_name
    await post(bot, wake_message(user, name, at, duration_minutes, is_nap))
    for g in member_groups(bot.cfg.groups, member):
        await post(bot, wake_message(user, name, at, duration_minutes, is_nap, Audience.GROUP, in_group=True), g.channel_id)
