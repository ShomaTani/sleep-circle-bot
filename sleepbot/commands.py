"""Phase 2: /edit /delete /privacy /leave /mystats。返信はすべて ephemeral。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from sleepbot import crypto
from sleepbot.config import JST
from sleepbot.db import SleepRecord, User
from sleepbot.privacy import Audience, Field, visible_fields
from sleepbot.sleeplog import (
    InvalidInput,
    InvalidSession,
    TimedRecord,
    build_record,
    decrypt_records,
    format_duration,
    parse_date,
    parse_manual,
)
from sleepbot.stats import duration_summary, format_clock, period_range, time_summary
from sleepbot.ui import SafeModal, SafeView

if TYPE_CHECKING:
    from sleepbot.bot import SleepBot

WEEKDAYS = "月火水木金土日"


def clip(text: str, limit: int = 1900) -> str:
    """Discord の 2000 文字制限に収める。"""
    return text if len(text) <= limit else text[: limit - 20].rsplit("\n", 1)[0] + "\n…（以下省略）"


def fmt_date(d) -> str:
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"


async def require_user(bot: SleepBot, interaction: discord.Interaction) -> User | None:
    user = bot.db.get_user(interaction.user.id)
    if user is None:
        await interaction.response.send_message("まだ参加していないよ。`/join` から始めてね。", ephemeral=True)
    return user


# ---------------------------------------------------------------- パスフレーズでの解錠


class UnlockLimiter:
    """パスフレーズの総当たりと、Argon2id による負荷を抑える。"""

    MAX_FAILURES = 5
    LOCK_SECONDS = 600

    def __init__(self) -> None:
        self._failures: dict[int, tuple[int, float]] = {}

    def locked_for(self, discord_id: int) -> int:
        count, until = self._failures.get(discord_id, (0, 0.0))
        if count >= self.MAX_FAILURES and until > time.monotonic():
            return int(until - time.monotonic()) + 1
        return 0

    def fail(self, discord_id: int) -> None:
        count, _ = self._failures.get(discord_id, (0, 0.0))
        if count >= self.MAX_FAILURES:
            count = 0
        self._failures[discord_id] = (count + 1, time.monotonic() + self.LOCK_SECONDS)

    def succeed(self, discord_id: int) -> None:
        self._failures.pop(discord_id, None)


OnUnlocked = Callable[[discord.Interaction, User, list[TimedRecord]], Awaitable[None]]


class UnlockModal(SafeModal, title="パスフレーズを入力"):
    passphrase = discord.ui.TextInput(label="パスフレーズ", min_length=1, max_length=128)

    def __init__(self, bot: SleepBot, records: list[SleepRecord], on_unlocked: OnUnlocked) -> None:
        super().__init__()
        self.bot = bot
        self.records = records
        self.on_unlocked = on_unlocked

    async def on_submit(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        wait = self.bot.unlock_limiter.locked_for(uid)
        if wait:
            await interaction.response.send_message(
                f"失敗が続いたので、{wait // 60 + 1}分ほど待ってから試してね。", ephemeral=True
            )
            return
        user = self.bot.db.get_user(uid)
        if user is None:
            await interaction.response.send_message("参加情報が見つからなかったよ。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            timed = await asyncio.to_thread(decrypt_records, user, self.passphrase.value, self.records)
        except crypto.WrongPassphrase:
            self.bot.unlock_limiter.fail(uid)
            await interaction.followup.send("パスフレーズが違うみたい。", ephemeral=True)
            return
        self.bot.unlock_limiter.succeed(uid)
        await self.on_unlocked(interaction, user, timed)


class UnlockButtonView(SafeView):
    def __init__(self, bot: SleepBot, owner_id: int, label: str, records: list[SleepRecord], on_unlocked: OnUnlocked):
        super().__init__(timeout=600)
        self.bot, self.owner_id, self.records, self.on_unlocked = bot, owner_id, records, on_unlocked
        self.unlock.label = label

    @discord.ui.button(label="🔒", style=discord.ButtonStyle.secondary)
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("本人だけが使えます。", ephemeral=True)
            return
        await interaction.response.send_modal(UnlockModal(self.bot, self.records, self.on_unlocked))


# ---------------------------------------------------------------- 公開設定


async def change_privacy(bot: SleepBot, interaction: discord.Interaction, user: User, share: bool) -> None:
    """/privacy と /join 直後の選択ボタンの共通処理。interaction.response で返事をする。"""
    if share != user.share_times:
        bot.db.set_share_times(user.discord_id, share)

    if not share:
        await interaction.response.send_message(
            "「睡眠時間だけ共有する」にしたよ。\n"
            "保存していた共有用の時刻は削除しました（暗号化された時刻は残っていて、あなただけが `/mystats` で見られます）。\n"
            "週次スタッツには次回の投稿から反映されます。",
            ephemeral=True,
        )
        return

    past = [r for r in bot.db.list_records(user.discord_id) if r.public_bedtime_utc is None]
    msg = "「時刻も共有する」にしたよ。これからの記録の入眠・起床時刻が、次回の週次スタッツから共有されます。"
    if not past:
        await interaction.response.send_message(msg, ephemeral=True)
        return

    async def backfill(inter: discord.Interaction, fresh: User, timed: list[TimedRecord]) -> None:
        current = bot.db.get_user(fresh.discord_id)
        if current is None or not visible_fields(current, Audience.PUBLIC) >= {Field.TIMES}:
            await inter.followup.send("いまは時刻を共有しない設定なので、何もしなかったよ。", ephemeral=True)
            return
        bot.db.set_public_times([(t.record.id, t.bedtime_utc, t.waketime_utc) for t in timed])
        await inter.followup.send(f"過去の記録 {len(timed)} 件の時刻も共有するようにしたよ。", ephemeral=True)

    await interaction.response.send_message(
        msg + f"\n\n過去の記録 {len(past)} 件の時刻は、いまは共有されていません。"
        "過去分も共有したいときは、下のボタンからパスフレーズを入力してね。",
        view=UnlockButtonView(bot, user.discord_id, "🔒 過去の記録も共有する", past, backfill),
        ephemeral=True,
    )


class PrivacyView(SafeView):
    def __init__(self, bot: SleepBot, owner_id: int) -> None:
        super().__init__(timeout=300)
        self.bot, self.owner_id = bot, owner_id

    async def _choose(self, interaction: discord.Interaction, share: bool) -> None:
        user = self.bot.db.get_user(interaction.user.id)
        if user is None or user.discord_id != self.owner_id:
            await interaction.response.send_message("本人だけが使えます。", ephemeral=True)
            return
        await change_privacy(self.bot, interaction, user, share)

    @discord.ui.button(label="時刻も共有する", style=discord.ButtonStyle.secondary)
    async def times(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, True)

    @discord.ui.button(label="睡眠時間だけ共有する", style=discord.ButtonStyle.primary)
    async def duration(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, False)


# ---------------------------------------------------------------- 確認ダイアログ


class ConfirmView(SafeView):
    def __init__(self, owner_id: int, label: str, on_confirm: Callable[[discord.Interaction], Awaitable[None]]):
        super().__init__(timeout=120)
        self.owner_id, self.on_confirm = owner_id, on_confirm
        self.confirm.label = label

    @discord.ui.button(label="OK", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            return
        self.stop()
        await self.on_confirm(interaction)

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="やめたよ。", view=None)


# ---------------------------------------------------------------- /mystats


def duration_report(bot: SleepBot, records: list[SleepRecord], start, end) -> str:
    s = duration_summary(records, bot.cfg.include_naps_in_total)
    lines = [f"**あなたのスタッツ（{fmt_date(start)}〜{fmt_date(end)}）**"]
    if not s.record_days and not s.nap_count:
        lines.append("この期間の記録はまだないよ。")
        return "\n".join(lines)
    lines += [
        f"記録日数: {s.record_days}日",
        f"平均睡眠時間: {format_duration(s.average_minutes) if s.average_minutes else '—'}",
        f"合計: {format_duration(s.total_minutes)}",
    ]
    if s.shortest_day and s.longest_day and s.record_days > 1:
        lines.append(
            f"最短: {fmt_date(s.shortest_day[0])} {format_duration(s.shortest_day[1])}"
            f" ／ 最長: {fmt_date(s.longest_day[0])} {format_duration(s.longest_day[1])}"
        )
    if s.nap_count:
        note = "合計に含む" if bot.cfg.include_naps_in_total else "合計には含めていない"
        lines.append(f"昼寝: {s.nap_count}回・{format_duration(s.nap_minutes)}（{note}）")
    lines.append("")
    lines += [f"`{fmt_date(d)}` {format_duration(m)}" for d, m in s.daily_minutes.items()]
    return "\n".join(lines)


def times_report(timed: list[TimedRecord]) -> str:
    t = time_summary([(x.record, x.bedtime_utc, x.waketime_utc) for x in timed])
    lines = [
        "**時刻のスタッツ（あなたにだけ表示）**",
        f"平均入眠: {format_clock(t.mean_bedtime)} ／ 平均起床: {format_clock(t.mean_waketime)}",
        f"入眠時刻のばらつき: {'±' + format_duration(t.bedtime_std) if t.bedtime_std is not None else '—（2回以上の記録が必要）'}",
        "ソーシャルジェットラグ（平日と休日の睡眠中央時刻の差）: "
        + (format_duration(t.social_jetlag) if t.social_jetlag is not None else "—（平日と休日の両方の記録が必要）"),
        "",
    ]
    for x in sorted(timed, key=lambda x: x.bedtime_utc):
        b, w = x.bedtime_utc.astimezone(JST), x.waketime_utc.astimezone(JST)
        nap = " 💤昼寝" if x.record.is_nap else ""
        lines.append(f"`{fmt_date(x.record.sleep_date)}` {b:%H:%M} → {w:%H:%M}（{format_duration(x.record.duration_minutes)}）{nap}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 登録


def register_phase2(bot: SleepBot) -> None:
    @bot.tree.command(name="edit", description="指定日の記録を手入力で登録・修正する（日付は起きた日）")
    @app_commands.describe(
        date="起きた日 YYYY-MM-DD",
        bedtime="寝た時刻 HH:MM（起床より遅い時刻なら前日の夜とみなす）",
        waketime="起きた時刻 HH:MM",
        add="その日の記録を置き換えずに追加する（昼寝など）",
    )
    async def edit(interaction: discord.Interaction, date: str, bedtime: str, waketime: str, add: bool = False) -> None:
        user = await require_user(bot, interaction)
        if user is None:
            return
        try:
            bed, wake = parse_manual(date, bedtime, waketime, interaction.created_at)
            rec, c = build_record(user, bed, wake, source="manual")
        except (InvalidInput, InvalidSession) as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        if add:
            bot.db.add_record(rec)
            note = "（追加）"
        else:
            removed = bot.db.replace_day(rec)
            note = f"（前の記録 {removed} 件を置き換え）" if removed else ""
        nap = "・昼寝" if c.is_nap else ""
        await interaction.response.send_message(
            f"{fmt_date(c.sleep_date)} の記録を登録したよ: {format_duration(c.duration_minutes)}{nap}{note}",
            ephemeral=True,
        )

    @bot.tree.command(name="delete", description="指定日の記録を削除する（日付は起きた日）")
    @app_commands.describe(date="起きた日 YYYY-MM-DD")
    async def delete(interaction: discord.Interaction, date: str) -> None:
        user = await require_user(bot, interaction)
        if user is None:
            return
        try:
            d = parse_date(date)
        except InvalidInput as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        n = len(bot.db.list_records(user.discord_id, d, d))
        if n == 0:
            await interaction.response.send_message(f"{fmt_date(d)} の記録はないよ。", ephemeral=True)
            return

        async def do_delete(inter: discord.Interaction) -> None:
            removed = bot.db.delete_day(user.discord_id, d)
            await inter.response.edit_message(content=f"{fmt_date(d)} の記録 {removed} 件を削除したよ。", view=None)

        await interaction.response.send_message(
            f"{fmt_date(d)} の記録 {n} 件を削除する？",
            view=ConfirmView(user.discord_id, "削除する", do_delete),
            ephemeral=True,
        )

    @bot.tree.command(name="privacy", description="入眠・起床時刻を共有するかどうかを変える")
    async def privacy(interaction: discord.Interaction) -> None:
        user = await require_user(bot, interaction)
        if user is None:
            return
        current = "時刻も共有する" if user.share_times else "睡眠時間だけ共有する"
        await interaction.response.send_message(
            f"いまの設定: **{current}**\n変更は次回の週次スタッツから反映されます。",
            view=PrivacyView(bot, user.discord_id),
            ephemeral=True,
        )

    @bot.tree.command(name="mystats", description="自分のスタッツを見る（自分にだけ表示）")
    @app_commands.describe(period="week=直近7日 / month=直近30日")
    @app_commands.choices(
        period=[app_commands.Choice(name="week", value="week"), app_commands.Choice(name="month", value="month")]
    )
    async def mystats(interaction: discord.Interaction, period: str = "week") -> None:
        user = await require_user(bot, interaction)
        if user is None:
            return
        start, end = period_range(period, datetime.now(JST).date())
        records = bot.db.list_records(user.discord_id, start, end)
        text = duration_report(bot, records, start, end)

        if not records or Field.TIMES not in visible_fields(user, Audience.SELF):
            await interaction.response.send_message(clip(text), ephemeral=True)
            return

        async def show_times(inter: discord.Interaction, _: User, timed: list[TimedRecord]) -> None:
            await inter.followup.send(clip(times_report(timed)), ephemeral=True)

        await interaction.response.send_message(
            clip(text) + "\n\n入眠・起床時刻も見るときは、下のボタンからパスフレーズを入力してね。",
            view=UnlockButtonView(bot, user.discord_id, "🔒 時刻も見る", records, show_times),
            ephemeral=True,
        )

    @bot.tree.command(name="leave", description="退会する（個人チャンネルと全記録を削除）")
    async def leave(interaction: discord.Interaction) -> None:
        user = await require_user(bot, interaction)
        if user is None:
            return

        async def do_leave(inter: discord.Interaction) -> None:
            bot.db.delete_user(user.discord_id)
            bot.pending.discard(user.discord_id)
            bot.unlock_limiter.succeed(user.discord_id)
            await inter.response.edit_message(content="退会したよ。記録はすべて削除しました。おつかれさま！", view=None)
            channel = bot.get_channel(user.channel_id) if user.channel_id else None
            if channel is not None:
                try:
                    await channel.delete(reason="sleep bot: /leave")
                except discord.HTTPException:
                    pass

        await interaction.response.send_message(
            "退会すると、個人チャンネルと**すべての記録**（睡眠時間・暗号化された時刻）を削除します。元に戻せません。",
            view=ConfirmView(user.discord_id, "退会して全部削除する", do_leave),
            ephemeral=True,
        )
