"""おやすみ中の入眠時刻: 再起動しても続き、DB に平文で残らず、起床で消えること。"""

import os
from datetime import datetime, timezone

from sleepbot.db import Database
from sleepbot.pending import PendingSleeps
from tests.conftest import make_user
from tests.test_storage_privacy import raw_db, time_fragments

KEY = os.urandom(32)
BED = datetime(2026, 10, 10, 15, 47, 23, tzinfo=timezone.utc)  # JST 0:47:23


def test_survives_restart(db, db_path):
    make_user(db, 1, share_times=False)
    PendingSleeps(db, KEY).start(1, BED)
    db.close()
    reopened = Database(str(db_path))  # 再起動を模す（新しい接続・新しいストア）
    p = PendingSleeps(reopened, KEY)
    assert p.has(1)
    assert p.pop(1) == BED
    assert not p.has(1)
    reopened.close()


def test_not_plain_in_db_and_deleted_on_wake(db, db_path):
    make_user(db, 1, share_times=False)
    p = PendingSleeps(db, KEY)
    p.start(1, BED)
    data = raw_db(db_path)
    for frag in time_fragments(BED):
        assert frag.encode() not in data, frag
    # メタデータ（作成時刻など）の列を持たない
    cols = {r["name"] for r in db.conn.execute("PRAGMA table_info(pending_sleeps)")}
    assert cols == {"discord_id", "sealed"}
    p.pop(1)
    assert db.conn.execute("SELECT COUNT(*) FROM pending_sleeps").fetchone()[0] == 0


def test_wrong_key_reads_nothing(db):
    make_user(db, 1, share_times=False)
    PendingSleeps(db, KEY).start(1, BED)
    other = PendingSleeps(db, os.urandom(32))
    assert other.pop(1) is None


def test_swapped_row_is_rejected(db):
    make_user(db, 1, share_times=False)
    make_user(db, 2, share_times=False)
    p = PendingSleeps(db, KEY)
    p.start(1, BED)
    # 1 の暗号文を 2 の行に移しても、2 の入眠時刻としては使わない
    db.put_pending(2, db.get_pending(1))
    assert p.pop(2) is None


def test_overwrite_and_discard(db):
    make_user(db, 1, share_times=False)
    p = PendingSleeps(db, KEY)
    p.start(1, BED)
    later = BED.replace(hour=16)
    p.start(1, later)
    assert p.pop(1) == later
    p.start(1, BED)
    p.discard(1)
    assert not p.has(1)


def test_leave_removes_pending(db):
    make_user(db, 1, share_times=False)
    PendingSleeps(db, KEY).start(1, BED)
    db.delete_user(1)
    assert db.conn.execute("SELECT COUNT(*) FROM pending_sleeps").fetchone()[0] == 0


def test_memory_only_without_key(db):
    make_user(db, 1, share_times=False)
    p = PendingSleeps(db, None)
    assert not p.persistent
    p.start(1, BED)
    assert db.conn.execute("SELECT COUNT(*) FROM pending_sleeps").fetchone()[0] == 0
    assert PendingSleeps(db, None).pop(1) is None  # 再起動で消える
    assert p.pop(1) == BED


def test_peek_does_not_remove(db):
    make_user(db, 1, share_times=False)
    p = PendingSleeps(db, KEY)
    p.start(1, BED)
    assert p.peek(1) == BED and p.has(1)
    assert PendingSleeps(db, os.urandom(32)).peek(1) is None
    m = PendingSleeps()
    m.start(1, BED)
    assert m.peek(1) == BED and m.has(1)
