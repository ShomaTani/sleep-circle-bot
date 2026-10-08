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

from sleepbot import crypto
from sleepbot.commands import UnlockLimiter, change_privacy, register_phase2
from sleepbot.config import JST, MAX_SESSION_HOURS, Config, load_config
from sleepbot.db import Database, User
from sleepbot.pending import PendingSleeps
from sleepbot.safelog import log, log_exception, setup_logging
from sleepbot.sleeplog import InvalidSession, format_duration, save_sleep
from sleepbot.ui import SafeModal, SafeTree, SafeView
from sleepbot.weekly import load_members, post_due, render_post

REPO_URL = "https://github.com/ShomaTani/sleep-circle-bot"

class SleepBot(discord.Client):
    def __init__(self, cfg: Config) -> None:
        intents = discord.Intents.none()
        intents.guilds = True  # チャンネル作成・取得に必要な最小限
        super().__init__(intents=intents)
        self.cfg = cfg
        self.db = Database(cfg.database_path)
        self.pending = PendingSleeps()
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

    async def on_ready(self) -> None:
        log.info("ready as %s", self.user)
        # 月曜 8:00 に止まっていた場合の取りこぼしを投稿する（投稿済みなら何もしない）
        await self.post_weekly_if_due()

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

    async def post_weekly_if_due(self) -> None:
        target = post_due(datetime.now(JST))
        if target is None:
            return
        start, end = target
        if not self.db.claim_week(start):
            return  # 投稿済み（または別の起動が投稿中）
        first = None
        try:
            members = load_members(self.db, start, end, self.cfg.include_naps_in_total)
            post = await asyncio.to_thread(render_post, members, start, end)
            channel = self.get_channel(self.cfg.stats_channel_id) or await self.fetch_channel(self.cfg.stats_channel_id)
            for text, files in post.messages:
                msg = await channel.send(
                    text,
                    files=[discord.File(io.BytesIO(png), filename=name) for name, png in files],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                first = first or msg
            self.db.mark_week_posted(start, first.id if first else 0)
            log.info("weekly stats posted for week starting %s", start.isoformat())
        except Exception as e:
            # 1通も送れていなければ解放して次の機会に再挑戦。途中まで送れていたら二重投稿を避けて諦める
            if first is None:
                self.db.release_week(start)
            log_exception("post_weekly", e)

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
    channel = await guild.create_text_channel(
        channel_name(member.name), category=category, overwrites=overwrites, reason="sleep bot: /join"
    )
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

    await channel.send(
        f"{member.mention} ようこそ！ここはあなた専用の記録チャンネルです。\n\n"
        "**大事なこと**\n"
        "・入眠・起床の時刻は、あなたのパスフレーズでしか復号できない形で保存されます（管理者も読めません）\n"
        "・**パスフレーズを忘れると、過去の時刻データは復元できません**（睡眠時間のデータは残ります）\n"
        "・睡眠時間（長さ）は全員に共有されます\n\n"
        "まず、時刻を共有するかどうかを選んでください（あとから `/privacy` で変えられます）。\n"
        "初期値は「睡眠時間だけ共有する」です。",
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

    @discord.ui.button(label="時刻も共有する", style=discord.ButtonStyle.secondary, custom_id="sleepbot:privacy:times")
    async def share_times(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, True)

    @discord.ui.button(
        label="睡眠時間だけ共有する", style=discord.ButtonStyle.primary, custom_id="sleepbot:privacy:duration"
    )
    async def duration_only(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, False)

    async def _choose(self, interaction: discord.Interaction, share: bool) -> None:
        user = self.bot.owner_of_channel(interaction)
        if user is None:
            await interaction.response.send_message("このボタンはチャンネルの持ち主だけが使えます。", ephemeral=True)
            return
        await change_privacy(self.bot, interaction, user, share)
        if user.panel_message_id is None:
            await post_panel(self.bot, interaction.channel, user.discord_id)


async def post_panel(bot: SleepBot, channel: discord.abc.Messageable, discord_id: int) -> None:
    msg = await channel.send(
        "**睡眠記録パネル**\n寝るときに 😴、起きたら ☀️ を押してね。押したことは誰にも通知されません。",
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
            result = save_sleep(self.bot.db, user, bedtime, waketime, source="button")
        except InvalidSession as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return
        text = f"{format_duration(result.duration_minutes)} 寝たよ"
        if result.is_nap:
            text += "（3時間未満なので昼寝として記録したよ）"
        await interaction.response.send_message(text, ephemeral=True)


class ConfirmOverwriteView(SafeView):
    def __init__(self, bot: SleepBot, discord_id: int) -> None:
        super().__init__(timeout=120)
        self.bot = bot
        self.discord_id = discord_id

    @discord.ui.button(label="上書きする", style=discord.ButtonStyle.danger)
    async def overwrite(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.bot.pending.start(self.discord_id, interaction.created_at)
        await interaction.response.edit_message(content="上書きしたよ。おやすみなさい 🌙", view=None)

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
