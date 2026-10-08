"""例外の中身をログやユーザーに出さない View / Modal / CommandTree。"""

from __future__ import annotations

import discord
from discord import app_commands

from sleepbot.safelog import log_exception

GENERIC_ERROR = "ごめん、うまく処理できなかった。少し待ってからもう一度試してね。"


async def send_error(interaction: discord.Interaction) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(GENERIC_ERROR, ephemeral=True)
        else:
            await interaction.response.send_message(GENERIC_ERROR, ephemeral=True)
    except discord.HTTPException:
        pass


class SafeView(discord.ui.View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        log_exception(f"view:{type(self).__name__}", error)
        await send_error(interaction)


class SafeModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log_exception(f"modal:{type(self).__name__}", error)
        await send_error(interaction)


class SafeTree(app_commands.CommandTree):
    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        log_exception(f"command:{interaction.command.name if interaction.command else '?'}", error)
        await send_error(interaction)
