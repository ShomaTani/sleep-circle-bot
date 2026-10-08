"""睡眠記録の計算と保存。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sleepbot import crypto
from sleepbot.config import JST, MAX_SESSION_HOURS, NAP_THRESHOLD_MINUTES
from sleepbot.db import Database, User


class InvalidSession(Exception):
    """起床が入眠より前、または長すぎる。時刻は持たない。"""


@dataclass(frozen=True)
class Computed:
    sleep_date: date
    duration_minutes: int
    is_nap: bool


def compute(bedtime_utc: datetime, waketime_utc: datetime) -> Computed:
    delta = waketime_utc - bedtime_utc
    if delta <= timedelta(0):
        raise InvalidSession("起床が入眠より前になっています")
    if delta >= timedelta(hours=MAX_SESSION_HOURS):
        raise InvalidSession(f"{MAX_SESSION_HOURS}時間以上の睡眠は記録できません")
    minutes = int(delta.total_seconds() // 60)
    return Computed(
        # 1回の睡眠は「起床した日」(JST) の記録
        sleep_date=waketime_utc.astimezone(JST).date(),
        duration_minutes=minutes,
        is_nap=minutes < NAP_THRESHOLD_MINUTES,
    )


def save_sleep(db: Database, user: User, bedtime_utc: datetime, waketime_utc: datetime, source: str) -> Computed:
    """長さは平文、時刻は本人の公開鍵で暗号化。時刻共有ONのときだけ平文の時刻も保存する。"""
    c = compute(bedtime_utc, waketime_utc)
    db.add_record(
        discord_id=user.discord_id,
        sleep_date=c.sleep_date,
        duration_minutes=c.duration_minutes,
        is_nap=c.is_nap,
        encrypted_times=crypto.seal_times(user.public_key, bedtime_utc, waketime_utc),
        public_bedtime_utc=bedtime_utc if user.share_times else None,
        public_waketime_utc=waketime_utc if user.share_times else None,
        source=source,
    )
    return c


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}時間{m}分" if h else f"{m}分"
