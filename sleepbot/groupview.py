"""/group で出すグループの様子（本人にだけ見える返事。チャンネルには出さない）。

出すのは、そのグループのロールを持つ参加者（ids）の分だけ。公開範囲の判定は visible_fields(GROUP) を通す。
"""

from __future__ import annotations

from datetime import date, datetime

from sleepbot.config import JST
from sleepbot.db import Database
from sleepbot.pending import PendingSleeps
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.sleeplog import format_duration
from sleepbot.weekly import fmt_date, safe_name


def _clock(dt: datetime) -> str:
    local = dt.astimezone(JST)
    return f"{local.hour}:{local.minute:02d}"


def group_status_text(db: Database, pending: PendingSleeps, ids: frozenset[int], today: date) -> str:
    sleeping, woke = [], []
    for u in db.list_users():
        if u.discord_id not in ids or Field.TIMES not in visible_fields(u, Audience.GROUP, in_group=True):
            continue
        name = safe_name(u.display_name)
        bed = pending.peek(u.discord_id)
        if bed is not None:
            sleeping.append((bed, name))
        for r in db.list_records(u.discord_id, today, today):
            if r.public_bedtime_utc and r.public_waketime_utc:
                woke.append((r.public_waketime_utc, name, r))
    lines = [f"👥 **グループの様子 {fmt_date(today)}**", "", "**いま寝ている**"]
    lines += [f"・{n}（{_clock(b)}〜）" for b, n in sorted(sleeping)] or ["・いない"]
    lines += ["", "**今日起きた**"]
    for w, n, r in sorted(woke, key=lambda x: x[0]):
        nap = "・昼寝" if r.is_nap else ""
        lines.append(f"・{n} {_clock(r.public_bedtime_utc)} → {_clock(w)}（{format_duration(r.duration_minutes)}{nap}）")
    if not woke:
        lines.append("・まだいない")
    return "\n".join(lines)
