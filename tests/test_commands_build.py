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
        assert names == {"join", "about", "edit", "delete", "privacy", "mystats", "leave"}
        # Persistent View は custom_id が固定で timeout なし
        view = RecordPanelView(bot)
        assert view.is_persistent()
        await bot.close()

    asyncio.run(run())
