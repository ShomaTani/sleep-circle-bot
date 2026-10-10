"""グループ（GROUPS で設定したロール → チャンネル）の判定。Bot は性別などの属性を持たず、ロールだけを見る。"""

from __future__ import annotations

import discord

from sleepbot.config import Group


def member_groups(groups: tuple[Group, ...], member: object) -> list[Group]:
    """その人が持つロールに対応するグループ。ロール情報がなければ空（＝グループ共有しない）。"""
    if not groups or not isinstance(member, discord.Member):
        return []
    role_ids = {r.id for r in member.roles}
    return [g for g in groups if g.role_id in role_ids]
