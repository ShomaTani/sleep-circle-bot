from datetime import datetime, timedelta, timezone

import pytest

from sleepbot.sleeplog import InvalidSession, compute, format_duration


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_sleep_date_is_wake_date_in_jst():
    # JST 10/7 23:30 → 10/8 06:30
    c = compute(utc(2026, 10, 7, 14, 30), utc(2026, 10, 7, 21, 30))
    assert c.sleep_date.isoformat() == "2026-10-08"
    assert c.duration_minutes == 420 and not c.is_nap


def test_nap_flag():
    c = compute(utc(2026, 10, 8, 4, 0), utc(2026, 10, 8, 5, 30))
    assert c.is_nap


def test_rejects_reverse_and_too_long():
    with pytest.raises(InvalidSession):
        compute(utc(2026, 10, 8, 5), utc(2026, 10, 8, 4))
    with pytest.raises(InvalidSession):
        start = utc(2026, 10, 8, 0)
        compute(start, start + timedelta(hours=20))


def test_format_duration():
    assert format_duration(402) == "6時間42分"
    assert format_duration(42) == "42分"
