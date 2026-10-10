"""グループ共有: ロールを持つ人の時刻はグループのチャンネルにだけ出て、全体には漏れないこと。"""

from datetime import date, datetime

import pytest

from sleepbot.config import JST, parse_groups
from sleepbot.daily import daily_due, daily_ranking
from sleepbot.groups import member_groups
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.realtime import sleep_message
from sleepbot.sleeplog import save_sleep
from sleepbot.weekly import build_sections, collect, load_group_members, render_group_post, weekly_report
from tests.conftest import make_user

START, END = date(2026, 10, 5), date(2026, 10, 11)


def jst(*a):
    return datetime(*a, tzinfo=JST)


# グループの人は特徴的な時刻で寝る（文字列検索で見つけやすくする）
GROUP_SLEEPS = [(jst(2026, 10, 4 + i, 22, 17), jst(2026, 10, 5 + i, 5, 43)) for i in range(7)]


@pytest.fixture
def setup(db):
    a = make_user(db, 1, share_times=False)  # グループのロールあり・全体には非公開
    b = make_user(db, 2, share_times=False)  # ロールなし・非公開
    db.conn.execute("UPDATE users SET joined_at = '2026-10-01'")
    db.conn.execute("UPDATE users SET display_name = 'グループさん' WHERE discord_id = 1")
    db.conn.execute("UPDATE users SET display_name = 'ソトさん' WHERE discord_id = 2")
    db.conn.commit()
    a, b = db.get_user(1), db.get_user(2)
    for bed, wake in GROUP_SLEEPS:
        save_sleep(db, a, bed, wake, "button", in_group=True)
        save_sleep(db, b, bed.replace(minute=3), wake.replace(minute=9), "button")
    return db


def test_parse_groups():
    gs = parse_groups("111:222, 333:444")
    assert [(g.role_id, g.channel_id) for g in gs] == [(111, 222), (333, 444)]
    assert parse_groups("") == ()
    with pytest.raises(SystemExit):
        parse_groups("abc:1")


def test_visible_fields_group(db):
    u = make_user(db, 1, share_times=False)
    assert visible_fields(u, Audience.GROUP, in_group=True) >= {Field.TIMES, Field.REALTIME}
    assert Field.TIMES not in visible_fields(u, Audience.GROUP, in_group=False)
    assert Field.TIMES not in visible_fields(u, Audience.PUBLIC)


def test_group_times_do_not_leak_to_public_weekly(setup):
    text = "\n".join(weekly_report(setup, START, END, include_naps=False))
    for frag in ("22:17", "5:43", "05:43"):
        assert frag not in text, frag
    sections = dict(
        build_sections(
            collect(setup.list_users(), {u.discord_id: setup.list_records(u.discord_id, START, END) for u in setup.list_users()}, False),
            START,
            END,
        )
    )
    assert "グループさん" in sections["duration"]  # 睡眠時間は全体に出る
    assert "グループさん" not in sections["times"]


def test_group_post_has_only_group_members(setup):
    members = load_group_members(setup, START, END, False, frozenset({1}))
    text = "\n".join(t for t, _ in render_group_post(members, START, END).messages)
    assert "グループさん" in text and "22:17" in text
    assert "ソトさん" not in text
    assert "平均睡眠" not in text  # 睡眠時間は全体のスタッツに任せる


def test_role_holder_without_role_is_not_shown(setup):
    # ロールを外された人（ids に含まれない）はグループ投稿にも出ない
    members = load_group_members(setup, START, END, False, frozenset())
    assert members == []


def test_clear_public_times(setup):
    assert setup.clear_public_times([1]) == 7
    assert all(r.public_bedtime_utc is None for r in setup.list_records(1))
    assert all(r.encrypted_times for r in setup.list_records(1))  # 暗号化済みは残る


def test_realtime_group_message(db):
    u = make_user(db, 1, share_times=False)
    at = jst(2026, 10, 10, 13, 5)
    assert sleep_message(u, "x", at) is None  # 全体には出ない
    assert sleep_message(u, "x", at, Audience.GROUP, in_group=True) == "😴 **x** がおやすみ（13:05）"
    assert sleep_message(u, "x", at, Audience.GROUP, in_group=False) is None


def test_member_groups_needs_member_roles():
    assert member_groups(parse_groups("1:2"), object()) == []


def test_daily_ranking(setup):
    text = daily_ranking(setup, date(2026, 10, 6), include_naps=False)
    lines = text.splitlines()
    assert "今日の睡眠ランキング" in lines[0]
    assert lines[1].startswith("🥇") and len(lines) == 3
    assert ":" not in "".join(lines[1:])  # 時刻は載らない
    assert daily_ranking(setup, date(2026, 9, 1), include_naps=False) is None


def test_daily_due():
    assert daily_due(jst(2026, 10, 10, 11, 59)) is None
    assert daily_due(jst(2026, 10, 10, 12, 0)) == date(2026, 10, 10)
    assert daily_due(jst(2026, 10, 10, 23, 59)) == date(2026, 10, 10)
