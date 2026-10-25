"""毎日 12:00（JST）の睡眠時間ランキング。今日起きた分（＝昨夜の睡眠）を長い順に並べる。

睡眠時間（長さ）だけを使うので、visible_fields() の DURATION が見える全員が対象。時刻は載せない。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sleepbot.config import JST
from sleepbot.db import Database
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.sleeplog import format_duration
from sleepbot.stats import duration_summary
from sleepbot.weekly import MEDALS, fmt_date, safe_name

POST_HOUR = 12
# 12:00 に止まっていた場合、その日のうちに起動すれば遅れて投稿する
CATCH_UP = timedelta(hours=12)


def daily_due(now: datetime) -> date | None:
    local = now.astimezone(JST)
    due = datetime(local.year, local.month, local.day, POST_HOUR, tzinfo=JST)
    return local.date() if due <= local < due + CATCH_UP else None


def daily_key(day: date) -> str:
    return f"daily-{day.isoformat()}"


def updated_ranking_due(now: datetime, day: date) -> bool:
    """/edit で day の記録が入ったとき、更新版のランキングを出すか。
    今日の分で、12時のランキングのあと（12:00 以降）だけ。12時より前の分は12時のランキングに入る。"""
    local = now.astimezone(JST)
    return day == local.date() and local.hour >= POST_HOUR


def daily_ranking(db: Database, day: date, include_naps: bool, updated: bool = False) -> str | None:
    """記録が1件もなければ None（投稿しない）。updated=True は /edit 後の更新版。"""
    rows = []
    for u in db.list_users():
        if Field.DURATION not in visible_fields(u, Audience.PUBLIC):
            continue
        s = duration_summary(db.list_records(u.discord_id, day, day), include_naps)
        if s.total_minutes:
            rows.append((s.total_minutes, u.display_name))
    if not rows:
        return None
    rows.sort(key=lambda r: (-r[0], r[1]))
    title = f"🔄 **今日の睡眠ランキング（更新） {fmt_date(day)}**" if updated else f"🛌 **今日の睡眠ランキング {fmt_date(day)}**"
    lines = [title]
    for i, (minutes, name) in enumerate(rows):
        mark = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
        lines.append(f"{mark} {safe_name(name)} {format_duration(minutes)}")
    return "\n".join(lines)
