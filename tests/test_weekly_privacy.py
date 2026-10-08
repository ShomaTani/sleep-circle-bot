"""週次投稿に、非公開ユーザーの時刻やそこから推測できる値が含まれないこと。"""

from datetime import date, datetime, timedelta

import pytest

from sleepbot.config import JST
from sleepbot.sleeplog import save_sleep
from sleepbot.stats import format_clock
from sleepbot.weekly import build_sections, collect, post_due, split_messages, weekly_report
from tests.conftest import make_user

START, END = date(2026, 10, 5), date(2026, 10, 11)  # 月〜日


def jst(*a):
    return datetime(*a, tzinfo=JST)


# 非公開ユーザーは「ありえない」ほど特徴的な時刻で寝る（文字列検索で見つけやすくする）
PRIVATE_SLEEPS = [(jst(2026, 10, 4 + i, 21, 13 + i), jst(2026, 10, 5 + i, 4, 47 - i)) for i in range(7)]
PUBLIC_SLEEPS = [(jst(2026, 10, 4 + i, 23, 30), jst(2026, 10, 5 + i, 7, 0)) for i in range(7)]


@pytest.fixture
def populated(db):
    priv = make_user(db, 1, share_times=False)
    pub = make_user(db, 2, share_times=True)
    db.conn.execute("UPDATE users SET display_name = 'ヒミツさん' WHERE discord_id = 1")
    db.conn.execute("UPDATE users SET display_name = 'オープンさん' WHERE discord_id = 2")
    db.conn.execute("UPDATE users SET joined_at = '2026-10-01'")
    db.conn.commit()
    priv, pub = db.get_user(1), db.get_user(2)
    for b, w in PRIVATE_SLEEPS:
        save_sleep(db, priv, b, w, "button")
    for b, w in PUBLIC_SLEEPS:
        save_sleep(db, pub, b, w, "button")
    return db


def private_time_strings():
    """非公開ユーザーの時刻・平均時刻が取りうる表記。"""
    out = set()
    for b, w in PRIVATE_SLEEPS:
        for dt in (b, w):
            out |= {dt.strftime("%H:%M"), f"{dt.hour}:{dt.minute:02d}"}
    # 平均入眠・起床（円周平均）の表記
    from sleepbot.stats import circular_mean

    for series in ([b for b, _ in PRIVATE_SLEEPS], [w for _, w in PRIVATE_SLEEPS]):
        mean = circular_mean([d.hour * 60 + d.minute for d in series])
        out.add(format_clock(mean))
    return out


def test_private_times_not_in_weekly_text(populated):
    text = "\n".join(weekly_report(populated, START, END, include_naps=False))
    for s in private_time_strings():
        assert s not in text, s
    # 公開ユーザーの時刻は載る
    assert "23:30" in text and "7:00" in text


def test_private_user_absent_from_times_section(populated):
    users = populated.list_users()
    records = {u.discord_id: populated.list_records(u.discord_id, START, END) for u in users}
    sections = dict(build_sections(collect(users, records, False), START, END))
    assert "ヒミツさん" in sections["duration"]  # 長さは全員分
    assert "ヒミツさん" not in sections["times"]  # 時刻・ばらつき・規則性ランキングには出ない
    assert "オープンさん" in sections["times"]


def test_private_user_ignored_even_if_plain_times_exist(populated):
    """万一 DB に平文の時刻が残っていても、公開範囲の判定で弾かれること（多重防御）。"""
    b, w = PRIVATE_SLEEPS[0]
    populated.conn.execute(
        "UPDATE sleep_records SET public_bedtime_utc = ?, public_waketime_utc = ? WHERE discord_id = 1",
        (b.isoformat(), w.isoformat()),
    )
    populated.conn.commit()
    text = "\n".join(weekly_report(populated, START, END, include_naps=False))
    for s in private_time_strings():
        assert s not in text, s
    assert "ヒミツさん" not in dict(
        build_sections(
            collect(populated.list_users(), {1: populated.list_records(1, START, END)}, False), START, END
        )
    )["times"]


def test_switching_to_private_hides_times_next_report(populated):
    populated.set_share_times(2, False)
    text = "\n".join(weekly_report(populated, START, END, include_naps=False))
    assert "23:30" not in text and "オープンさん" in text
    assert "時刻を共有している人の記録がありませんでした" in text


def test_ranking_and_duration_content(populated):
    text = "\n".join(weekly_report(populated, START, END, include_naps=False))
    assert "よく寝た人ランキング" in text and "🥇 オープンさん 7時間30分" in text
    assert "一番規則正しかった人" in text


def test_names_cannot_mention_or_format(db):
    u = make_user(db, 3, share_times=False)
    db.conn.execute("UPDATE users SET display_name = '@everyone **x**', joined_at = '2026-10-01' WHERE discord_id = 3")
    db.conn.commit()
    save_sleep(db, db.get_user(3), jst(2026, 10, 5, 23), jst(2026, 10, 6, 6), "button")
    text = "\n".join(weekly_report(db, START, END, include_naps=False))
    assert "@everyone" not in text


def test_messages_fit_discord_limit():
    sections = [("duration", "\n".join(f"・member{i}: 平均 7時間0分" for i in range(300)))]
    msgs = split_messages(sections)
    assert len(msgs) > 1 and all(len(m) <= 2000 for m in msgs)


def test_post_due():
    assert post_due(jst(2026, 10, 12, 7, 59)) is None  # 月曜 8:00 前
    assert post_due(jst(2026, 10, 12, 8, 0)) == (START, END)
    assert post_due(jst(2026, 10, 14, 7, 59)) == (START, END)  # 48時間以内なら遅れて投稿
    assert post_due(jst(2026, 10, 14, 8, 0)) is None  # それ以降は投稿しない
    assert post_due(jst(2026, 10, 9, 0, 53)) is None  # 金曜の初回起動で前週を投稿しない


def test_empty_week_has_no_records(db):
    from sleepbot.weekly import has_any_record, load_members

    make_user(db, 9, share_times=False)
    assert not has_any_record(load_members(db, START, END, False))


def test_claim_prevents_double_post(db):
    assert db.claim_week(START) is True
    assert db.claim_week(START) is False
    db.release_week(START)
    assert db.claim_week(START) is True
