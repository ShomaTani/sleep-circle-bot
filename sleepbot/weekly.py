"""週次スタッツ（共有チャンネルに出すもの）。

出力はすべて visible_fields(user, Audience.PUBLIC) を通す。
時刻は「時刻も共有する」人の平文の時刻（public_*_utc）だけから計算し、暗号化された時刻には触れない。

    python -m sleepbot.weekly [YYYY-MM-DD]   # 投稿される内容を表示するだけ（投稿しない）。画像は data/preview/ に保存
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime, timedelta

from sleepbot.config import JST
from sleepbot.db import Database, SleepRecord, User
from sleepbot.images import Sleep, sleep_bands, to_png, weekly_heatmap
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.sleeplog import format_duration
from sleepbot.stats import DurationSummary, TimeSummary, duration_summary, format_clock, previous_week, time_summary

WEEKDAYS = "月火水木金土日"
MEDALS = ["🥇", "🥈", "🥉"]
# ランキングに載る最低記録数（1日だけ長く寝た人が1位にならないように）
MIN_DAYS_FOR_RANKING = 3


def fmt_date(d: date) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


def safe_name(name: str) -> str:
    """表示名を Markdown・メンションとして解釈させない。"""
    out = name.replace("@", "@​")
    for ch in "\\*_~`|>#[]()":
        out = out.replace(ch, "\\" + ch)
    return out[:32]


@dataclass(frozen=True)
class MemberWeek:
    user: User
    duration: DurationSummary
    times: TimeSummary | None  # 時刻を共有していない人は必ず None
    public_sleeps: list[Sleep] | None  # 同上。睡眠帯グラフ用


def collect(
    users: list[User], records_by_user: dict[int, list[SleepRecord]], include_naps: bool
) -> list[MemberWeek]:
    members = []
    for u in users:
        fields = visible_fields(u, Audience.PUBLIC)
        recs = records_by_user.get(u.discord_id, [])
        dur = duration_summary(recs, include_naps) if Field.DURATION in fields else duration_summary([], include_naps)
        times = sleeps = None
        if Field.TIMES in fields:
            timed = [
                (r, r.public_bedtime_utc, r.public_waketime_utc)
                for r in recs
                if r.public_bedtime_utc is not None and r.public_waketime_utc is not None
            ]
            times = time_summary(timed)
            sleeps = [Sleep(r.sleep_date, b, w, r.is_nap) for r, b, w in timed]
        members.append(MemberWeek(u, dur, times, sleeps))
    return members


def _ranked(items: list[tuple[str, str]]) -> list[str]:
    return [f"{MEDALS[i] if i < len(MEDALS) else f'{i + 1}.'} {name} {value}" for i, (name, value) in enumerate(items)]


def build_sections(members: list[MemberWeek], start: date, end: date) -> list[tuple[str, str]]:
    """(見出しキー, 本文) のリスト。キーは "duration" か "times"（テストで中身を区別するため）。"""
    sections: list[tuple[str, str]] = []
    head = f"📊 **週次スタッツ {fmt_date(start)}〜{fmt_date(end)}**"

    # ---- 長さ（全員）
    by_avg = sorted(members, key=lambda m: (-(m.duration.average_minutes or -1), m.user.display_name))
    lines = [head, "", "**睡眠時間**"]
    for m in by_avg:
        d = m.duration
        name = safe_name(m.user.display_name)
        if d.record_days == 0:
            lines.append(f"・{name}: 記録なし")
            continue
        nap = f" ／ 昼寝 {d.nap_count}回" if d.nap_count else ""
        lines.append(
            f"・{name}: 平均 {format_duration(d.average_minutes)} ／ 合計 {format_duration(d.total_minutes)}"
            f" ／ {d.record_days}日{nap}"
        )

    days = [start + timedelta(days=i) for i in range(7)]
    grid = ["```", " ".join(f"{WEEKDAYS[d.weekday()]:>3}" for d in days)]
    for m in by_avg:
        if m.duration.record_days == 0:
            continue
        cells = []
        for d in days:
            v = m.duration.daily_minutes.get(d)
            cells.append(f"{v / 60:4.1f}" if v is not None else "   -")
        grid.append(" ".join(cells) + "  " + m.user.display_name.replace("`", "'").replace("@", "@\u200b")[:16])
    grid.append("```")
    if len(grid) > 3:
        lines += ["", "**曜日ごと（時間）**", *grid]

    ranked = [m for m in by_avg if m.duration.record_days >= MIN_DAYS_FOR_RANKING]
    lines += ["", f"**🛌 よく寝た人ランキング**（記録{MIN_DAYS_FOR_RANKING}日以上）"]
    lines += _ranked([(safe_name(m.user.display_name), format_duration(m.duration.average_minutes)) for m in ranked]) or [
        "該当者なし"
    ]
    sections.append(("duration", "\n".join(lines)))

    # ---- 時刻（共有を選んだ人だけ）
    sharing = [m for m in members if m.times is not None and m.times.sleeps > 0]
    lines = ["**🕘 時刻（「時刻も共有する」を選んだ人のみ）**"]
    if not sharing:
        lines.append("今週は時刻を共有している人の記録がありませんでした。")
    for m in sorted(sharing, key=lambda m: m.user.display_name):
        t = m.times
        assert t is not None
        parts = [f"平均入眠 {format_clock(t.mean_bedtime)}", f"平均起床 {format_clock(t.mean_waketime)}"]
        if t.bedtime_std is not None:
            parts.append(f"入眠のばらつき ±{format_duration(t.bedtime_std)}")
        if t.social_jetlag is not None:
            parts.append(f"ソーシャルジェットラグ {format_duration(t.social_jetlag)}")
        lines.append(f"・{safe_name(m.user.display_name)}: " + " ／ ".join(parts))

    regular = sorted(
        (m for m in sharing if m.times.bedtime_std is not None and m.times.sleeps >= MIN_DAYS_FOR_RANKING),
        key=lambda m: m.times.bedtime_std,
    )
    if sharing:
        lines += ["", f"**⏰ 一番規則正しかった人**（入眠時刻のばらつきが小さい順・{MIN_DAYS_FOR_RANKING}回以上）"]
        lines += _ranked([(safe_name(m.user.display_name), f"±{format_duration(m.times.bedtime_std)}") for m in regular]) or [
            "該当者なし"
        ]
    sections.append(("times", "\n".join(lines)))
    return sections


def split_messages(sections: list[tuple[str, str]], limit: int = 1900) -> list[str]:
    """Discord の 2000 文字制限に合わせて分ける。コードブロックの途中では切らない。"""
    messages: list[str] = []
    for _, body in sections:
        chunk = ""
        for block in _blocks(body):
            if len(chunk) + len(block) + 1 > limit and chunk:
                messages.append(chunk.rstrip())
                chunk = ""
            chunk += block + "\n"
        if chunk.strip():
            messages.append(chunk.rstrip())
    return messages


def _blocks(body: str) -> list[str]:
    out, buf, in_code = [], [], False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
            buf.append(line)
            if not in_code:
                out.append("\n".join(buf))
                buf = []
            continue
        if in_code:
            buf.append(line)
        else:
            out.append(line)
    if buf:
        out.append("\n".join(buf))
    return out


def build_figures(members: list[MemberWeek], start: date, end: date) -> dict:
    """{"duration": Figure, "times": Figure | None}。睡眠帯は public_sleeps を持つ人（時刻共有）だけ。"""
    with_records = sorted(
        (m for m in members if m.duration.record_days),
        key=lambda m: (-(m.duration.average_minutes or 0), m.user.display_name),
    )
    heat = weekly_heatmap([(m.user.display_name, m.duration.daily_minutes) for m in with_records], start)
    sharing = [m for m in members if m.public_sleeps]
    bands = (
        sleep_bands(
            [(m.user.display_name, m.public_sleeps) for m in sorted(sharing, key=lambda m: m.user.display_name)],
            start, end, "睡眠帯（「時刻も共有する」を選んだ人のみ）",
        )
        if sharing
        else None
    )
    return {"duration": heat if with_records else None, "times": bands}


@dataclass(frozen=True)
class WeeklyPost:
    messages: list[tuple[str, list[tuple[str, bytes]]]]  # (本文, [(ファイル名, PNG)])


def load_members(db: Database, start: date, end: date, include_naps: bool) -> list[MemberWeek]:
    users = [u for u in db.list_users() if u.joined_at <= end.isoformat()]
    records = {u.discord_id: db.list_records(u.discord_id, start, end) for u in users}
    return collect(users, records, include_naps)


def render_post(members: list[MemberWeek], start: date, end: date) -> WeeklyPost:
    """本文と画像。画像は各セクションの最後のメッセージに付ける。DB に触らないのでスレッドで呼べる。"""
    figures = build_figures(members, start, end)
    out: list[tuple[str, list[tuple[str, bytes]]]] = []
    for key, body in build_sections(members, start, end):
        chunks = split_messages([(key, body)])
        for i, text in enumerate(chunks):
            files = []
            if i == len(chunks) - 1 and figures.get(key) is not None:
                files.append((f"{key}-{start.isoformat()}.png", to_png(figures[key])))
            out.append((text, files))
    return WeeklyPost(out)


def weekly_post(db: Database, start: date, end: date, include_naps: bool) -> WeeklyPost:
    return render_post(load_members(db, start, end, include_naps), start, end)


def weekly_report(db: Database, start: date, end: date, include_naps: bool) -> list[str]:
    """本文だけ（テスト・確認用）。"""
    return [text for text, _ in weekly_post(db, start, end, include_naps).messages]


def post_due(now: datetime) -> tuple[date, date] | None:
    """いま投稿すべき週（前週）。今週の月曜 8:00 JST より前なら None。"""
    local = now.astimezone(JST)
    monday = local.date() - timedelta(days=local.weekday())
    due = datetime(monday.year, monday.month, monday.day, 8, 0, tzinfo=JST)
    if local < due:
        return None
    return previous_week(local.date())


if __name__ == "__main__":
    from sleepbot.config import load_config

    cfg = load_config()
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(JST).date()
    s, e = previous_week(today)
    post = weekly_post(Database(cfg.database_path), s, e, cfg.include_naps_in_total)
    for text, files in post.messages:
        print(text)
        for name, png in files:
            out = Path("data/preview") / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png)
            print(f"[画像] {out}")
        print("\n---\n")
