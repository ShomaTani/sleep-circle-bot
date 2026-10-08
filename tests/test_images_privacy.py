"""週次投稿の画像に、非公開ユーザーの時刻（睡眠帯）や名前入りの時刻情報が含まれないこと。"""

from datetime import date

from matplotlib.patches import Rectangle
from matplotlib.text import Text

from sleepbot.images import _band_span, month_calendar, to_png
from sleepbot.weekly import build_figures, load_members, render_post
from tests.test_weekly_privacy import END, PRIVATE_SLEEPS, PUBLIC_SLEEPS, START, populated  # noqa: F401


def texts(fig):
    return [t.get_text() for t in fig.findobj(Text) if t.get_text()]


def bars(fig):
    """睡眠帯のバー（barh が作る Rectangle）の (左端, 幅)。"""
    out = []
    for ax in fig.axes:
        for p in ax.patches:
            if isinstance(p, Rectangle) and p.get_width() > 0:
                out.append((round(p.get_x(), 4), round(p.get_width(), 4)))
    return out


def figures(db):
    return build_figures(load_members(db, START, END, False), START, END)


def test_band_chart_excludes_private_user(populated):  # noqa: F811
    fig = figures(populated)["times"]
    assert fig is not None
    assert not any("ヒミツさん" in t for t in texts(fig))
    assert any("オープンさん" in t for t in texts(fig))
    # バーは公開ユーザーの睡眠の分だけ
    assert len(bars(fig)) == len(PUBLIC_SLEEPS)


def test_no_bar_matches_private_sleep(populated):  # noqa: F811
    from sleepbot.images import Sleep
    from sleepbot.stats import DAY_MIN  # noqa: F401

    fig = figures(populated)["times"]
    drawn = set(bars(fig))
    for b, w in PRIVATE_SLEEPS:
        span = _band_span(Sleep(w.date(), b, w, False))
        assert span is not None
        assert (round(span[0], 4), round(span[1] - span[0], 4)) not in drawn


def test_band_chart_ignores_plain_times_of_private_user(populated):  # noqa: F811
    b, w = PRIVATE_SLEEPS[0]
    populated.conn.execute(
        "UPDATE sleep_records SET public_bedtime_utc = ?, public_waketime_utc = ? WHERE discord_id = 1",
        (b.isoformat(), w.isoformat()),
    )
    populated.conn.commit()
    fig = figures(populated)["times"]
    assert not any("ヒミツさん" in t for t in texts(fig))
    assert len(bars(fig)) == len(PUBLIC_SLEEPS)


def test_no_band_chart_when_nobody_shares(populated):  # noqa: F811
    populated.set_share_times(2, False)
    assert figures(populated)["times"] is None


def test_heatmap_has_durations_only(populated):  # noqa: F811
    fig = figures(populated)["duration"]
    labels = texts(fig)
    assert "ヒミツさん" in labels  # 長さは全員分
    assert not any(":" in t for t in labels)  # 時刻表記（HH:MM）が一切ない


def test_png_has_no_embedded_text(populated):  # noqa: F811
    post = render_post(load_members(populated, START, END, False), START, END)
    pngs = [png for _, files in post.messages for _, png in files]
    assert len(pngs) == 2
    for png in pngs:
        assert png.startswith(b"\x89PNG")
        assert b"tEXt" not in png and b"iTXt" not in png
        assert "ヒミツさん".encode() not in png


def test_month_calendar_renders():
    daily = {date(2026, 10, 1): 420, date(2026, 10, 3): 300}
    fig = month_calendar(daily, date(2026, 9, 10), date(2026, 10, 9), "t")
    assert "7:00" in texts(fig) and "10/1" in texts(fig)
    to_png(fig)
