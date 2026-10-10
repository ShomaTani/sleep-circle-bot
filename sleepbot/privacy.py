"""公開範囲の判定。出力処理はすべて visible_fields() を経由する。"""

from __future__ import annotations

from enum import Enum

from sleepbot.db import User


class Audience(Enum):
    SELF = "self"  # 本人だけに見える場所（ephemeral・個人チャンネル）
    PUBLIC = "public"  # 共有チャンネル（全員が見える）
    GROUP = "group"  # グループのチャンネル（GROUPS のロールを持つ人だけが見える）


class Field(Enum):
    DURATION = "duration"  # 睡眠時間（長さ）・記録日数・昼寝フラグ
    TIMES = "times"  # 入眠・起床時刻と、そこから推測できる値（平均時刻・ばらつき・規則性・睡眠帯）
    REALTIME = "realtime"  # 就寝・起床をその場で共有チャンネル（REPORT_CHANNEL_ID）に投稿する


def visible_fields(user: User, audience: Audience, in_group: bool = False) -> frozenset[Field]:
    """in_group: Audience.GROUP のとき、その人がそのグループのロールを持っているか。
    グループのチャンネルでは、ロールを持つ人は時刻まで自動で共有される（運用で決めた方針）。"""
    if audience is Audience.GROUP and in_group:
        return frozenset({Field.DURATION, Field.TIMES, Field.REALTIME})
    if audience is Audience.SELF:
        return frozenset({Field.DURATION, Field.TIMES})
    if user.share_times and user.share_realtime:
        return frozenset({Field.DURATION, Field.TIMES, Field.REALTIME})
    if user.share_times:
        return frozenset({Field.DURATION, Field.TIMES})
    return frozenset({Field.DURATION})


def can_show_times(user: User, audience: Audience, in_group: bool = False) -> bool:
    return Field.TIMES in visible_fields(user, audience, in_group)
