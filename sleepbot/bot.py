"""Discord Bot 本体（/join・プライバシー設定・記録パネル・/about）。Phase 2 のコマンドは commands.py。

個人向けの返信はすべて ephemeral か個人チャンネル内。共有チャンネルには何も送らない。
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import subprocess
from datetime import datetime, time, timedelta

import discord
from discord import app_commands
from discord.ext import tasks

from sleepbot import crypto, realtime
from sleepbot.commands import UnlockLimiter, change_privacy, register_phase2
from sleepbot.config import JST, MAX_SESSION_HOURS, Config, load_config
from sleepbot.db import Database, User
from sleepbot.groups import member_groups
from sleepbot.guide import guide_text
from sleepbot.pending import PendingSleeps
from sleepbot.safelog import log, log_exception, setup_logging
from sleepbot.sleeplog import InvalidSession, format_duration, save_sleep
from sleepbot.ui import SafeModal, SafeTree, SafeView
from sleepbot.daily import daily_due, daily_key, daily_ranking
from sleepbot.weekly import has_any_record, load_members, post_due, render_post

REPO_URL = "https://github.com/ShomaTani/sleep-circle-bot"

class SleepBot(discord.Client):
    def __init__(self, cfg: Config) -> None:
        intents = discord.Intents.none()
        intents.guilds = True  # チャンネル作成・取得に必要な最小限
        super().__init__(intents=intents)
        self.cfg = cfg
        self.db = Database(cfg.database_path)
        self.pending = PendingSleeps(self.db, cfg.pending_key)
        self.unlock_limiter = UnlockLimiter()
        self.tree = SafeTree(self)

    async def setup_hook(self) -> None:
        # Persistent View: 再起動後も既存メッセージのボタンが動く
        self.add_view(PrivacyChoiceView(self))
        self.add_view(RecordPanelView(self))
        register_commands(self)
        register_phase2(self)
        guild = discord.Object(id=self.cfg.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        self.weekly_job.start()
        self.daily_job.start()

    async def on_ready(self) -> None:
        log.info("ready as %s", self.user)
        if not self.pending.persistent:
            log.warning("PENDING_KEY が未設定なので、おやすみ中の記録は再起動で消えます（README 参照）")
        if not isinstance(self.get_channel(self.cfg.category_id), discord.CategoryChannel):
            log.warning("CATEGORY_ID のカテゴリが見えません。Bot のロールに「チャンネルを見る」などを許可してください（README 参照）")
        if self.get_channel(self.cfg.stats_channel_id) is None:
            log.warning("STATS_CHANNEL_ID のチャンネルが見えません")
        # 止まっていた場合の取りこぼしを投稿する（投稿済みなら何もしない）
        await self.post_weekly_if_due()
        await self.post_daily_if_due()

    @tasks.loop(time=time(8, 0, tzinfo=JST))
    async def weekly_job(self) -> None:
        if datetime.now(JST).weekday() == 0:
            await self.post_weekly_if_due()

    @weekly_job.before_loop
    async def _before_weekly(self) -> None:
        await self.wait_until_ready()

    @weekly_job.error
    async def _weekly_error(self, error: BaseException) -> None:
        log_exception("weekly_job", error)

    @tasks.loop(time=time(12, 0, tzinfo=JST))
    async def daily_job(self) -> None:
        await self.post_daily_if_due()

    @daily_job.before_loop
    async def _before_daily(self) -> None:
        await self.wait_until_ready()

    @daily_job.error
    async def _daily_error(self, error: BaseException) -> None:
        log_exception("daily_job", error)

    async def post_daily_if_due(self) -> None:
        day = daily_due(datetime.now(JST))
        if day is None or not self.db.claim_key(daily_key(day)):
            return
        try:
            text = daily_ranking(self.db, day, self.cfg.include_naps_in_total)
            if text is None:
                return  # 記録なし。確保したままにしてその日は試さない
            channel = self.get_channel(self.cfg.stats_channel_id) or await self.fetch_channel(self.cfg.stats_channel_id)
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
            log.info("daily ranking posted for %s", day.isoformat())
        except Exception as e:
            self.db.release_key(daily_key(day))
            log_exception("post_daily", e)

    async def group_member_ids(self) -> dict[int, frozenset[int]]:
        """グループ（role_id）ごとに、そのロールを持つ参加者の discord_id。ロールは投稿の時点で確認する。"""
        guild = self.get_guild(self.cfg.guild_id)
        result: dict[int, set[int]] = {g.role_id: set() for g in self.cfg.groups}
        if guild is None or not self.cfg.groups:
            return {k: frozenset(v) for k, v in result.items()}
        for u in self.db.list_users():
            member = guild.get_member(u.discord_id)
            if member is None:
                try:
                    member = await guild.fetch_member(u.discord_id)
                except discord.HTTPException:
                    continue
            for g in member_groups(self.cfg.groups, member):
                result[g.role_id].add(u.discord_id)
        return {k: frozenset(v) for k, v in result.items()}

    async def clear_stale_plain_times(self) -> None:
        """時刻共有もグループもやめた人（ロールを外れた人を含む）の平文の時刻を消す。週次処理のときに行う。"""
        ids_by_role = await self.group_member_ids()
        in_any = frozenset().union(*ids_by_role.values()) if ids_by_role else frozenset()
        stale = [u.discord_id for u in self.db.list_users() if not u.share_times and u.discord_id not in in_any]
        if self.db.clear_public_times(stale):
            log.info("cleared plain times of members who stopped sharing")

    async def on_error(self, event_method: str, /, *args: object, **kwargs: object) -> None:
        import sys

        exc = sys.exc_info()[1]
        if exc is not None:
            log_exception(f"event:{event_method}", exc)

    def owner_of_channel(self, interaction: discord.Interaction) -> User | None:
        """押した人が参加者で、かつ自分の個人チャンネルで押しているときだけ User を返す。"""
        user = self.db.get_user(interaction.user.id)
        if user is None or user.channel_id != interaction.channel_id:
            return None
        return user


# ---------------------------------------------------------------- /join


class PassphraseModal(SafeModal, title="パスフレーズを設定"):
    passphrase = discord.ui.TextInput(
        label="パスフレーズ（8文字以上）",
        placeholder="忘れると過去の入眠・起床時刻は誰にも復元できません",
        min_length=crypto.MIN_PASSPHRASE_LENGTH,
        max_length=128,
    )
    confirm = discord.ui.TextInput(
        label="もう一度入力",
        min_length=crypto.MIN_PASSPHRASE_LENGTH,
        max_length=128,
    )

    def __init__(self, bot: SleepBot) -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        p1, p2 = self.passphrase.value, self.confirm.value
        if p1 != p2:
            await interaction.response.send_message(
                "2回の入力が一致しなかったよ。もう一度 `/join` してね。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        keys = await asyncio.to_thread(crypto.create_user_keys, p1)
        del p1, p2
        await finish_join(self.bot, interaction, keys)


async def finish_join(bot: SleepBot, interaction: discord.Interaction, keys: crypto.UserKeys) -> None:
    guild = interaction.guild
    member = interaction.user
    assert guild is not None and isinstance(member, discord.Member)

    if bot.db.get_user(member.id) is not None:
        await interaction.followup.send("もう参加済みだよ。", ephemeral=True)
        return

    category = guild.get_channel(bot.cfg.category_id)
    if not isinstance(category, discord.CategoryChannel):
        await interaction.followup.send("Bot の設定（CATEGORY_ID）が正しくないみたい。管理者に伝えてね。", ephemeral=True)
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_messages=True,  # ピン留め
            attach_files=True,
            embed_links=True,
        ),
    }
    try:
        channel = await guild.create_text_channel(
            channel_name(member.name), category=category, overwrites=overwrites, reason="sleep bot: /join"
        )
    except discord.Forbidden:
        log.warning("cannot create channel in category: missing permissions (see README)")
        await interaction.followup.send(
            "Bot にカテゴリの権限がなくて、チャンネルを作れなかったよ。管理者に README の「サーバー側の準備」を確認してもらってね。",
            ephemeral=True,
        )
        return
    try:
        bot.db.add_user(
            discord_id=member.id,
            display_name=member.display_name,
            public_key=keys.public_key,
            encrypted_private_key=keys.encrypted_private_key,
            kdf_salt=keys.kdf_salt,
            kdf_params=keys.kdf_params,
        )
        bot.db.set_channel(member.id, channel.id)
    except Exception:
        await channel.delete(reason="sleep bot: /join failed")
        raise

    # 使い方の案内（消えない通常メッセージ。ピン留めして、いつでも見返せるようにする）
    welcome = await channel.send(
        f"{member.mention} ようこそ！ここはあなた専用の記録チャンネルです。\n\n" + guide_text(bot.cfg),
        allowed_mentions=discord.AllowedMentions(users=[member]),
        suppress_embeds=True,
    )
    await welcome.pin(reason="sleep bot: guide")
    await channel.send(
        "**まず、どこまで共有するかを選んでね**（あとから `/privacy` で変えられます。初期値は「睡眠時間だけ」）\n"
        "・**睡眠時間だけ共有する**: 全体には睡眠時間（長さ）だけ\n"
        "・**時刻も共有する**: 週次スタッツに寝た・起きた時刻も載る\n"
        "・**リアルタイムでも共有する**: さらに、寝た・起きたをその場で投稿する",
        view=PrivacyChoiceView(bot),
    )
    await interaction.followup.send(f"{channel.mention} を作ったよ。", ephemeral=True)


def channel_name(username: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]", "", username.lower())[:80] or "member"
    return f"sleep-{slug}"


# ---------------------------------------------------------------- プライバシー設定


class PrivacyChoiceView(SafeView):
    def __init__(self, bot: SleepBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    # custom_id は既存メッセージのボタンと互換（times / duration は Phase 1 から）
    @discord.ui.button(
        label="睡眠時間だけ共有する", style=discord.ButtonStyle.primary, custom_id="sleepbot:privacy:duration", row=0
    )
    async def duration_only(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, "duration")

    @discord.ui.button(label="時刻も共有する", style=discord.ButtonStyle.secondary, custom_id="sleepbot:privacy:times", row=0)
    async def share_times(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, "times")

    @discord.ui.button(
        label="リアルタイムでも共有する", style=discord.ButtonStyle.secondary, custom_id="sleepbot:privacy:realtime", row=0
    )
    async def share_realtime(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, "realtime")

    async def _choose(self, interaction: discord.Interaction, level: str) -> None:
        user = self.bot.owner_of_channel(interaction)
        if user is None:
            await interaction.response.send_message("このボタンはチャンネルの持ち主だけが使えます。", ephemeral=True)
            return
        await change_privacy(self.bot, interaction, user, level)
        if user.panel_message_id is None:
            await post_panel(self.bot, interaction.channel, user.discord_id)


async def post_panel(bot: SleepBot, channel: discord.abc.Messageable, discord_id: int) -> None:
    msg = await channel.send(
        "**睡眠記録パネル**\n寝るときに 😴、起きたら ☀️ を押してね。"
        "「リアルタイムでも共有する」を選んでいなければ、押したことは誰にも通知されません。",
        view=RecordPanelView(bot),
    )
    await msg.pin(reason="sleep bot: record panel")
    bot.db.set_panel_message(discord_id, msg.id)


# ---------------------------------------------------------------- 記録パネル


class RecordPanelView(SafeView):
    def __init__(self, bot: SleepBot) -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="おやすみ", emoji="😴", style=discord.ButtonStyle.primary, custom_id="sleepbot:panel:sleep")
    async def sleep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        user = self.bot.owner_of_channel(interaction)
        if user is None:
            await interaction.response.send_message("このパネルはチャンネルの持ち主だけが使えます。", ephemeral=True)
            return
        if self.bot.pending.has(user.discord_id):
            await interaction.response.send_message(
                "まだ「おはよう」していない記録があるよ。上書きして今から寝たことにする？",
                view=ConfirmOverwriteView(self.bot, user.discord_id),
                ephemeral=True,
            )
            return
        self.bot.pending.start(user.discord_id, interaction.created_at)
        await interaction.response.send_message("おやすみなさい 🌙", ephemeral=True)
        await realtime.announce_sleep(self.bot, user, interaction.user, interaction.created_at)

    @discord.ui.button(label="おはよう", emoji="☀️", style=discord.ButtonStyle.success, custom_id="sleepbot:panel:wake")
    async def wake(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        user = self.bot.owner_of_channel(interaction)
        if user is None:
            await interaction.response.send_message("このパネルはチャンネルの持ち主だけが使えます。", ephemeral=True)
            return
        bedtime = self.bot.pending.pop(user.discord_id)
        if bedtime is None:
            await interaction.response.send_message(
                "入眠の記録が見つからなかったよ（Bot の再起動で消えた可能性があります）。\n"
                "`/edit` で入眠・起床時刻を手入力してね。",
                ephemeral=True,
            )
            return
        waketime = interaction.created_at
        if waketime - bedtime >= timedelta(hours=MAX_SESSION_HOURS):
            await interaction.response.send_message(
                f"入眠から{MAX_SESSION_HOURS}時間以上経っていたので、この記録は無効にしたよ。\n"
                "`/edit` で正しい時刻を入力してね。",
                ephemeral=True,
            )
            return
        try:
            in_group = bool(member_groups(self.bot.cfg.groups, interaction.user))
            result = save_sleep(self.bot.db, user, bedtime, waketime, source="button", in_group=in_group)
        except InvalidSession as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        text = f"{format_duration(result.duration_minutes)} 寝たよ"
        if result.is_nap:
            text += "（3時間未満なので昼寝として記録したよ）"
        await interaction.response.send_message(text, ephemeral=True)
        await realtime.announce_wake(
            self.bot, user, interaction.user, waketime, result.duration_minutes, result.is_nap
        )


class ConfirmOverwriteView(SafeView):
    def __init__(self, bot: SleepBot, discord_id: int) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.discord_id = discord_id

    @discord.ui.button(label="上書きする", style=discord.ButtonStyle.danger)
    async def overwrite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.bot.pending.start(self.discord_id, interaction.created_at)
        await interaction.response.edit_message(content="上書きしたよ。おやすみなさい 🌙", view=None)
        user = self.bot.db.get_user(self.discord_id)
        if user is not None:
            await realtime.announce_sleep(self.bot, user, interaction.user, interaction.created_at)

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="前の記録をそのまま残したよ。", view=None)


# ---------------------------------------------------------------- コマンド


def running_commit() -> str:
    for name in ("RAILWAY_GIT_COMMIT_SHA", "SOURCE_COMMIT", "GIT_COMMIT"):
        if os.environ.get(name):
            return os.environ[name][:12]
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return "unknown"
        sha = out.stdout.strip()[:12]
        return sha + ("（未コミットの変更あり）" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def register_commands(bot: SleepBot) -> None:
    @bot.tree.command(name="join", description="睡眠記録に参加する（専用チャンネルを作ります）")
    @app_commands.guild_only()
    async def join(interaction: discord.Interaction) -> None:
        if bot.db.get_user(interaction.user.id) is not None:
            await interaction.response.send_message("もう参加済みだよ。", ephemeral=True)
            return
        await interaction.response.send_modal(PassphraseModal(bot))

    @bot.tree.command(name="guide", description="使い方の案内をもう一度見る（自分にだけ表示）")
    async def guide(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(guide_text(bot.cfg), ephemeral=True, suppress_embeds=True)

    @bot.tree.command(name="about", description="この Bot のソースコードと、いま動いているバージョン")
    async def about(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"ソースコード: {REPO_URL}\n動いているコミット: `{running_commit()}`\n"
            f"保存の仕組みは {REPO_URL}/blob/main/PRIVACY.md にあります。",
            ephemeral=True,
        )


def main() -> None:
    setup_logging()
    cfg = load_config()
    bot = SleepBot(cfg)
    bot.run(cfg.token, log_handler=None)
