from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from sleepbot import crypto
from sleepbot.commands import UnlockLimiter, duration_report
from sleepbot.config import JST
from sleepbot.sleeplog import InvalidInput, build_record, decrypt_records, parse_manual, save_sleep
from tests.conftest import PASSPHRASE, make_user
from tests.test_storage_privacy import raw_db, time_fragments

NOW = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)  # JST 10/9 12:00


def jst(*a):
    return datetime(*a, tzinfo=JST)


# ---- /edit の入力解釈


def test_bedtime_later_than_waketime_is_previous_night():
    bed, wake = parse_manual("2026-10-08", "23:30", "07:00", NOW)
    assert bed == jst(2026, 10, 7, 23, 30) and wake == jst(2026, 10, 8, 7, 0)


def test_after_midnight_bedtime_is_same_day():
    bed, wake = parse_manual("2026-10-08", "1:15", "7:00", NOW)
    assert bed == jst(2026, 10, 8, 1, 15)


def test_fullwidth_colon_ok_and_bad_formats_rejected():
    parse_manual("2026-10-08", "23：30", "07：00", NOW)
    for args in [("2026/10/08", "23:30", "07:00"), ("2026-10-08", "25:00", "07:00"), ("2026-10-08", "2330", "07:00")]:
        with pytest.raises(InvalidInput):
            parse_manual(*args, NOW)


def test_future_rejected():
    with pytest.raises(InvalidInput):
        parse_manual("2026-10-10", "23:00", "07:00", NOW)


# ---- 置き換え・追加・削除


def test_replace_day_and_add(db):
    u = make_user(db, 1, share_times=False)
    save_sleep(db, u, jst(2026, 10, 7, 23), jst(2026, 10, 8, 6), "button")
    save_sleep(db, u, jst(2026, 10, 8, 13), jst(2026, 10, 8, 14), "button")  # 昼寝
    rec, _ = build_record(u, *parse_manual("2026-10-08", "23:30", "07:30", NOW), source="manual")
    assert db.replace_day(rec) == 2
    recs = db.list_records(1)
    assert len(recs) == 1 and recs[0].duration_minutes == 480 and recs[0].source == "manual"
    nap, _ = build_record(u, *parse_manual("2026-10-08", "13:00", "14:00", NOW), source="manual")
    db.add_record(nap)
    assert len(db.list_records(1)) == 2
    assert db.delete_day(1, date(2026, 10, 8)) == 2
    assert db.list_records(1) == []


def test_manual_entry_is_encrypted_for_private_user(db, db_path):
    u = make_user(db, 2, share_times=False)
    bed, wake = parse_manual("2026-10-08", "23:47", "06:53", NOW)
    rec, _ = build_record(u, bed, wake, source="manual")
    db.add_record(rec)
    data = raw_db(db_path)
    for frag in time_fragments(bed, wake):
        assert frag.encode() not in data, frag


# ---- 過去分の公開（private → public）


def test_backfill_decrypts_with_passphrase(db):
    u = make_user(db, 3, share_times=False)
    bed, wake = jst(2026, 10, 7, 23, 10), jst(2026, 10, 8, 6, 40)
    save_sleep(db, u, bed, wake, "button")
    db.set_share_times(3, True)
    recs = db.list_records(3)
    assert recs[0].public_bedtime_utc is None  # 切り替えただけでは過去分は公開されない
    timed = decrypt_records(db.get_user(3), PASSPHRASE, recs)
    db.set_public_times([(t.record.id, t.bedtime_utc, t.waketime_utc) for t in timed])
    r = db.list_records(3)[0]
    assert r.public_bedtime_utc == bed and r.public_waketime_utc == wake


def test_backfill_ignored_for_private_user(db):
    u = make_user(db, 4, share_times=False)
    save_sleep(db, u, jst(2026, 10, 7, 23), jst(2026, 10, 8, 6), "button")
    r = db.list_records(4)[0]
    db.set_public_times([(r.id, jst(2026, 10, 7, 23), jst(2026, 10, 8, 6))])
    assert db.list_records(4)[0].public_bedtime_utc is None


def test_backfill_needs_correct_passphrase(db):
    u = make_user(db, 5, share_times=True)
    save_sleep(db, u, jst(2026, 10, 7, 23), jst(2026, 10, 8, 6), "button")
    with pytest.raises(crypto.WrongPassphrase):
        decrypt_records(u, "not my passphrase", db.list_records(5))


# ---- 退会


def test_leave_removes_everything(db, db_path):
    u = make_user(db, 6, share_times=True)
    bed, wake = jst(2026, 10, 7, 23, 21), jst(2026, 10, 8, 6, 37)
    save_sleep(db, u, bed, wake, "button")
    db.delete_user(6)
    assert db.get_user(6) is None
    assert db.conn.execute("SELECT COUNT(*) FROM sleep_records").fetchone()[0] == 0
    data = raw_db(db_path)
    for frag in time_fragments(bed, wake):
        assert frag.encode() not in data, frag
    assert u.public_key not in data


# ---- パスフレーズ試行の制限


def test_unlock_limiter():
    lim = UnlockLimiter()
    for _ in range(lim.MAX_FAILURES - 1):
        lim.fail(1)
    assert lim.locked_for(1) == 0
    lim.fail(1)
    assert lim.locked_for(1) > 0
    assert lim.locked_for(2) == 0
    lim.succeed(1)
    assert lim.locked_for(1) == 0


# ---- /mystats のテキスト（時刻を含まないこと）


def test_duration_report_has_no_times(db):
    u = make_user(db, 7, share_times=False)
    bed, wake = jst(2026, 10, 7, 23, 47), jst(2026, 10, 8, 6, 53)
    save_sleep(db, u, bed, wake, "button")
    bot = SimpleNamespace(cfg=SimpleNamespace(include_naps_in_total=False))
    text = duration_report(bot, db.list_records(7), date(2026, 10, 2), date(2026, 10, 8))
    assert "7時間6分" in text
    for frag in ("23:47", "6:53", "06:53"):
        assert frag not in text
