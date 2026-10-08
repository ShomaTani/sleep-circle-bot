"""集計（純粋関数）。

- duration_summary: 長さだけから計算する。全員分を共有してよい
- time_summary: 入眠・起床時刻から計算する。visible_fields() で TIMES が見える相手にだけ出す
時刻の平均・ばらつきは 0時をまたぐので円周統計（24時間を円とみなす）で計算する。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sleepbot.config import JST
from sleepbot.db import SleepRecord

DAY_MIN = 1440


# ---- 長さ


@dataclass(frozen=True)
class DurationSummary:
    record_days: int
    total_minutes: int
    average_minutes: float | None
    nap_count: int
    nap_minutes: int
    daily_minutes: dict[date, int]  # 睡眠日ごとの合計（集計に使った分）
    shortest_day: tuple[date, int] | None
    longest_day: tuple[date, int] | None


def duration_summary(records: list[SleepRecord], include_naps: bool) -> DurationSummary:
    daily: dict[date, int] = defaultdict(int)
    nap_count = nap_minutes = 0
    for r in records:
        if r.is_nap:
            nap_count += 1
            nap_minutes += r.duration_minutes
            if not include_naps:
                continue
        daily[r.sleep_date] += r.duration_minutes
    total = sum(daily.values())
    days = len(daily)
    ordered = sorted(daily.items(), key=lambda kv: (kv[1], kv[0]))
    return DurationSummary(
        record_days=days,
        total_minutes=total,
        average_minutes=total / days if days else None,
        nap_count=nap_count,
        nap_minutes=nap_minutes,
        daily_minutes=dict(sorted(daily.items())),
        shortest_day=ordered[0] if ordered else None,
        longest_day=ordered[-1] if ordered else None,
    )


# ---- 時刻


def _clock_minutes(dt: datetime) -> float:
    local = dt.astimezone(JST)
    return local.hour * 60 + local.minute + local.second / 60


def circular_mean(minutes: list[float]) -> float | None:
    if not minutes:
        return None
    angles = [m / DAY_MIN * 2 * math.pi for m in minutes]
    s = sum(math.sin(a) for a in angles)
    c = sum(math.cos(a) for a in angles)
    if math.hypot(s, c) < 1e-9:
        return None
    return (math.atan2(s, c) / (2 * math.pi) * DAY_MIN) % DAY_MIN


def circular_std(minutes: list[float]) -> float | None:
    """標準偏差（分）。2件未満なら None。"""
    if len(minutes) < 2:
        return None
    angles = [m / DAY_MIN * 2 * math.pi for m in minutes]
    r = math.hypot(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles)) / len(angles)
    r = min(max(r, 1e-12), 1.0)
    return math.sqrt(-2 * math.log(r)) / (2 * math.pi) * DAY_MIN


def clock_diff(a: float, b: float) -> float:
    """時計上の差（分、-720〜720）。a が b より遅ければ正。"""
    return (a - b + DAY_MIN / 2) % DAY_MIN - DAY_MIN / 2


@dataclass(frozen=True)
class TimeSummary:
    sleeps: int
    mean_bedtime: float | None  # 0時からの分
    mean_waketime: float | None
    bedtime_std: float | None  # 分
    social_jetlag: float | None  # 休日と平日の睡眠中央時刻の差（分、絶対値）


def time_summary(times: list[tuple[SleepRecord, datetime, datetime]]) -> TimeSummary:
    """昼寝は除外する。休日＝起床日が土日。"""
    main = [(r, b, w) for r, b, w in times if not r.is_nap]
    beds = [_clock_minutes(b) for _, b, _ in main]
    wakes = [_clock_minutes(w) for _, _, w in main]
    mids_work, mids_free = [], []
    for r, b, w in main:
        mid = _clock_minutes(b + (w - b) / 2)
        (mids_free if r.sleep_date.weekday() >= 5 else mids_work).append(mid)
    mw, mf = circular_mean(mids_work), circular_mean(mids_free)
    return TimeSummary(
        sleeps=len(main),
        mean_bedtime=circular_mean(beds),
        mean_waketime=circular_mean(wakes),
        bedtime_std=circular_std(beds),
        social_jetlag=abs(clock_diff(mf, mw)) if mw is not None and mf is not None else None,
    )


def format_clock(minutes: float | None) -> str:
    if minutes is None:
        return "—"
    m = round(minutes) % DAY_MIN
    return f"{m // 60}:{m % 60:02d}"


# ---- 期間


def period_range(period: str, today: date) -> tuple[date, date]:
    """/mystats の期間。week=直近7日、month=直近30日（どちらも今日を含む）。"""
    days = 7 if period == "week" else 30
    return today - timedelta(days=days - 1), today


def previous_week(today: date) -> tuple[date, date]:
    """週次スタッツの対象。前週の月曜〜日曜。"""
    this_monday = today - timedelta(days=today.weekday())
    return this_monday - timedelta(days=7), this_monday - timedelta(days=1)
