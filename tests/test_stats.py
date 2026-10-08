from datetime import date, datetime

import pytest

from sleepbot.config import JST
from sleepbot.db import SleepRecord
from sleepbot.stats import (
    circular_mean,
    circular_std,
    duration_summary,
    format_clock,
    period_range,
    previous_week,
    time_summary,
)


def rec(d, minutes, nap=False):
    return SleepRecord(0, 1, d, minutes, nap, b"", None, None, "button")


def test_duration_summary_sums_per_day_and_separates_naps():
    rs = [rec(date(2026, 10, 6), 400), rec(date(2026, 10, 6), 60, nap=True), rec(date(2026, 10, 7), 300)]
    s = duration_summary(rs, include_naps=False)
    assert s.record_days == 2 and s.total_minutes == 700 and s.average_minutes == 350
    assert s.nap_count == 1 and s.nap_minutes == 60
    s2 = duration_summary(rs, include_naps=True)
    assert s2.total_minutes == 760 and s2.daily_minutes[date(2026, 10, 6)] == 460


def test_circular_mean_across_midnight():
    assert format_clock(circular_mean([23 * 60, 60])) == "0:00"
    assert circular_std([23 * 60, 60]) == pytest.approx(60, rel=0.02)
    assert circular_std([60]) is None


def test_social_jetlag():
    def t(d, bh, wh):  # 起床日 d、入眠は前日 bh 時、起床 wh 時
        bed = datetime(d.year, d.month, d.day - 1, bh, tzinfo=JST)
        wake = datetime(d.year, d.month, d.day, wh, tzinfo=JST)
        return (rec(d, int((wake - bed).total_seconds() // 60)), bed, wake)

    # 平日(月 10/5): 23→7 中央3:00 / 休日(土 10/10): 1日ずれて 1:00→9:00 中央5:00
    weekday = t(date(2026, 10, 5), 23, 7)
    sat_bed = datetime(2026, 10, 10, 1, tzinfo=JST)
    sat_wake = datetime(2026, 10, 10, 9, tzinfo=JST)
    weekend = (rec(date(2026, 10, 10), 480), sat_bed, sat_wake)
    s = time_summary([weekday, weekend])
    assert s.social_jetlag == pytest.approx(120)
    assert format_clock(s.mean_bedtime) == "0:00"


def test_naps_excluded_from_time_summary():
    bed = datetime(2026, 10, 8, 13, tzinfo=JST)
    s = time_summary([(rec(date(2026, 10, 8), 60, nap=True), bed, bed.replace(hour=14))])
    assert s.sleeps == 0 and s.mean_bedtime is None


def test_periods():
    assert period_range("week", date(2026, 10, 8)) == (date(2026, 10, 2), date(2026, 10, 8))
    assert period_range("month", date(2026, 10, 8))[0] == date(2026, 9, 9)
    # 2026-10-12 は月曜 → 前週 10/5(月)〜10/11(日)
    assert previous_week(date(2026, 10, 12)) == (date(2026, 10, 5), date(2026, 10, 11))
    assert previous_week(date(2026, 10, 14)) == (date(2026, 10, 5), date(2026, 10, 11))
