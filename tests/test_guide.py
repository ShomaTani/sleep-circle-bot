from sleepbot.config import Config, parse_groups
from sleepbot.guide import guide_text


def cfg(**kw):
    base = dict(token="x", guild_id=1, stats_channel_id=222, category_id=3, database_path=":memory:", include_naps_in_total=False)
    base.update(kw)
    return Config(**base)


def test_guide_fits_and_covers_basics():
    text = guide_text(cfg(report_channel_id=333, groups=parse_groups("10:444,11:555")))
    assert len(text) + 60 < 2000  # あいさつの行を足しても Discord の上限に収まる
    for s in ("😴", "☀️", "/mystats", "/edit", "`/`", "/privacy", "/group", "<#222>", "<#333>"):
        assert s in text, s
    # グループの情報はチャンネルに出さないので、グループのチャンネルは案内しない
    assert "<#444>" not in text and "<#555>" not in text


def test_guide_omits_unconfigured_features():
    text = guide_text(cfg())
    assert "リアルタイム" not in text and "/group" not in text
