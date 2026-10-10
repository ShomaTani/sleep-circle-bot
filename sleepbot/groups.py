"""グループ（GROUPS で設定したロール）の判定。Bot は性別などの属性を持たず、ロールだけを見る。

グループの情報はチャンネルには出さず、/group の本人にだけ見える返事でだけ出す
（サーバーの持ち主・管理者はどのチャンネルも見られるため）。
複数のグループのロールを持つ人には、どのグループの情報も出さない（どちらにも数えない）。
"""

from __future__ import annotations

from collections.abc import Iterable

import discord

from sleepbot.config import Group


def groups_for_roles(groups: tuple[Group, ...], role_ids: Iterable[int]) -> list[Group]:
    held = set(role_ids)
    mine = [g for g in groups if g.role_id in held]
    return mine if len(mine) == 1 else []


def member_groups(groups: tuple[Group, ...], member: object) -> list[Group]:
    """その人が属するグループ（0 か 1 個）。ロール情報がなければ空（＝グループ共有しない）。"""
    if not groups or not isinstance(member, discord.Member):
        return []
    return groups_for_roles(groups, (r.id for r in member.roles))
