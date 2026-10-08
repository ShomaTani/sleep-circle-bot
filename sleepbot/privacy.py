"""公開範囲の判定。出力処理はすべて visible_fields() を経由する。"""

from __future__ import annotations

from enum import Enum

from sleepbot.db import User


class Audience(Enum):
    SELF = "self"  # 本人だけに見える場所（ephemeral・個人チャンネル）
    PUBLIC = "public"  # 共有チャンネル


class Field(Enum):
    DURATION = "duration"  # 睡眠時間（長さ）・記録日数・昼寝フラグ
    TIMES = "times"  # 入眠・起床時刻と、そこから推測できる値（平均時刻・ばらつき・規則性・睡眠帯）


def visible_fields(user: User, audience: Audience) -> frozenset[Field]:
    if audience is Audience.SELF:
        return frozenset({Field.DURATION, Field.TIMES})
    if user.share_times:
        return frozenset({Field.DURATION, Field.TIMES})
    return frozenset({Field.DURATION})


def can_show_times(user: User, audience: Audience) -> bool:
    return Field.TIMES in visible_fields(user, audience)
