"""DB ファイルを直接読んでも、非公開ユーザーの時刻が平文で存在しないこと。"""

from datetime import datetime, timezone

from sleepbot.config import JST
from sleepbot.sleeplog import save_sleep
from tests.conftest import make_user

BED = datetime(2026, 10, 7, 15, 12, 34, tzinfo=timezone.utc)  # JST 00:12:34
WAKE = datetime(2026, 10, 7, 22, 3, 56, tzinfo=timezone.utc)  # JST 07:03:56


def time_fragments(*dts):
    """DB に現れてはいけない文字列（UTC/JST の各表現）。"""
    out = set()
    for dt in dts:
        for d in (dt.astimezone(timezone.utc), dt.astimezone(JST)):
            out |= {d.isoformat(), d.strftime("%H:%M:%S"), d.strftime("%H:%M"), str(int(d.timestamp()))}
    return out


def raw_db(db_path):
    data = db_path.read_bytes()
    for suffix in ("-journal", "-wal"):
        extra = db_path.with_name(db_path.name + suffix)
        if extra.exists():
            data += extra.read_bytes()
    return data


def test_private_user_times_not_in_db_file(db, db_path):
    user = make_user(db, 1, share_times=False)
    save_sleep(db, user, BED, WAKE, source="button")
    data = raw_db(db_path)
    for frag in time_fragments(BED, WAKE):
        assert frag.encode() not in data, frag
    rec = db.list_records(1)[0]
    assert rec.public_bedtime_utc is None and rec.public_waketime_utc is None
    assert rec.duration_minutes == 411


def test_public_user_times_are_stored_plain(db):
    user = make_user(db, 2, share_times=True)
    save_sleep(db, user, BED, WAKE, source="button")
    rec = db.list_records(2)[0]
    assert rec.public_bedtime_utc == BED and rec.public_waketime_utc == WAKE


def test_switching_to_private_removes_plain_times(db, db_path):
    user = make_user(db, 3, share_times=True)
    save_sleep(db, user, BED, WAKE, source="button")
    db.set_share_times(3, False)
    rec = db.list_records(3)[0]
    assert rec.public_bedtime_utc is None and rec.public_waketime_utc is None
    assert rec.encrypted_times  # 暗号化済みは残る
    data = raw_db(db_path)
    for frag in time_fragments(BED, WAKE):
        assert frag.encode() not in data, frag


def test_record_metadata_has_no_time_of_day(db):
    user = make_user(db, 4, share_times=False)
    save_sleep(db, user, BED, WAKE, source="button")
    row = db.conn.execute("SELECT created_at, updated_at FROM sleep_records").fetchone()
    # 日付のみ（YYYY-MM-DD）。ボタン記録の作成時刻＝起床時刻になるため
    assert len(row["created_at"]) == 10 and len(row["updated_at"]) == 10
