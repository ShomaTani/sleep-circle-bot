"""スラッシュコマンドと View がネットワークなしで組み立てられること。"""

import asyncio

from sleepbot.bot import RecordPanelView, SleepBot, register_commands
from sleepbot.commands import register_phase2
from sleepbot.config import Config


def test_commands_register(tmp_path):
    async def run():
        cfg = Config("x", 1, 2, 3, str(tmp_path / "db.sqlite"), False)
        bot = SleepBot(cfg)
        register_commands(bot)
        register_phase2(bot)
        names = {c.name for c in bot.tree.get_commands()}
        assert names == {"join", "guide", "about", "edit", "delete", "privacy", "mystats", "group", "leave"}
        # Persistent View は custom_id が固定で timeout なし
        view = RecordPanelView(bot)
        assert view.is_persistent()
        from sleepbot.bot import PrivacyChoiceView

        ids = {c.custom_id for c in PrivacyChoiceView(bot).children}
        # 既存メッセージのボタン（times / duration）と互換のまま、realtime を追加
        assert ids == {"sleepbot:privacy:duration", "sleepbot:privacy:times", "sleepbot:privacy:realtime"}
        await bot.close()

    asyncio.run(run())


def test_startup_jobs_run_without_network(tmp_path):
    """on_ready で呼ぶ取りこぼし投稿の処理が存在し、記録ゼロなら何も投稿せずに終わること。"""

    async def run():
        cfg = Config("x", 1, 2, 3, str(tmp_path / "db.sqlite"), False)
        bot = SleepBot(cfg)
        await bot.post_weekly_if_due()
        await bot.post_daily_if_due()
        await bot.clear_stale_plain_times()
        await bot.close()

    asyncio.run(run())
