"""リアルタイム共有: 選んだ人だけが投稿され、時刻共有をやめるとリアルタイムも止まること。"""

import sqlite3
from datetime import datetime

from sleepbot.config import JST
from sleepbot.db import Database
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.realtime import sleep_message, wake_message
from tests.conftest import make_user

AT = datetime(2026, 10, 10, 23, 41, tzinfo=JST)


def realtime_user(db, uid=1):
    make_user(db, uid, share_times=True)
    db.set_privacy(uid, share_times=True, share_realtime=True)
    return db.get_user(uid)


def test_visible_fields_levels(db):
    assert Field.REALTIME not in visible_fields(make_user(db, 1, share_times=False), Audience.PUBLIC)
    assert Field.REALTIME not in visible_fields(make_user(db, 2, share_times=True), Audience.PUBLIC)
    assert Field.REALTIME in visible_fields(realtime_user(db, 3), Audience.PUBLIC)


def test_messages_only_for_realtime_users(db):
    private = make_user(db, 1, share_times=False)
    weekly_only = make_user(db, 2, share_times=True)
    live = realtime_user(db, 3)
    for u in (private, weekly_only):
        assert sleep_message(u, "x", AT) is None
        assert wake_message(u, "x", AT, 402, False) is None
    assert sleep_message(live, "しょうま", AT) == "😴 **しょうま** がおやすみ（23:41）"
    assert wake_message(live, "しょうま", AT, 402, False) == "☀️ **しょうま** がおきた（23:41・6時間42分）"
    assert "昼寝" in wake_message(live, "しょうま", AT, 50, True)


def test_names_are_neutralized(db):
    live = realtime_user(db)
    assert "@everyone" not in sleep_message(live, "@everyone", AT)


def test_realtime_requires_times(db):
    make_user(db, 1, share_times=False)
    db.set_privacy(1, share_times=False, share_realtime=True)
    assert db.get_user(1).share_realtime is False


def test_stopping_times_stops_realtime(db):
    realtime_user(db)
    db.set_share_times(1, False)
    u = db.get_user(1)
    assert not u.share_times and not u.share_realtime
    assert sleep_message(u, "x", AT) is None


def test_times_level_turns_realtime_off(db):
    realtime_user(db)
    db.set_privacy(1, share_times=True, share_realtime=False)
    assert db.get_user(1).share_realtime is False


def test_old_database_gets_new_column(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.execute(
        """CREATE TABLE users (discord_id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, channel_id INTEGER,
           panel_message_id INTEGER, share_times INTEGER NOT NULL DEFAULT 0, public_key BLOB NOT NULL,
           encrypted_private_key BLOB NOT NULL, kdf_salt BLOB NOT NULL, kdf_params TEXT NOT NULL, joined_at TEXT NOT NULL)"""
    )
    c.execute("INSERT INTO users VALUES (1, 'a', 10, 11, 1, x'00', x'00', x'00', '{}', '2026-10-09')")
    c.commit()
    c.close()
    db = Database(str(path))
    u = db.get_user(1)
    assert u.share_times is True and u.share_realtime is False
    db.close()
