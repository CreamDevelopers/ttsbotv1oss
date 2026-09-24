from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core import ui


def _on_off(value: object) -> str:
    return "ON" if value else "OFF"


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    settings_group = app_commands.Group(
        name="settings", description="サーバーの読み上げ設定", guild_only=True
    )

    @settings_group.command(name="show", description="現在のサーバー設定を表示します")
    async def show(self, interaction: discord.Interaction):
        s = await self.bot.db.get_guild_settings(interaction.guild_id)
        channel = interaction.guild.get_channel(s["text_channel_id"]) if s["text_channel_id"] else None
        body = ui.field_lines(
            [
                ("読み上げチャンネル", channel.mention if channel else "未設定（`/join` または `/read_here` で設定）"),
                ("名前を読み上げる", _on_off(s["read_display_name"])),
                ("最大読み上げ文字数", f"{s['max_length']} 文字"),
                ("入退室アナウンス", _on_off(s["notify_join_leave"])),
                ("VCに人が入ったら自動接続", _on_off(s["auto_join"])),
                ("無人時に自動退出", _on_off(s["auto_leave_when_alone"])),
            ]
        )
        await interaction.response.send_message(
            view=ui.notice(
                "サーバー設定",
                body,
                emoji="⚙️",
                footer="地震速報の設定は `/earthquake show` で確認できます。",
            ),
            ephemeral=True,
        )

    @settings_group.command(name="read_name", description="ユーザー名を読み上げるかどうかを切り替えます")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def read_name(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_settings(interaction.guild_id, read_display_name=int(enabled))
        await interaction.response.send_message(
            view=ui.success("設定を変更しました", f"名前の読み上げを **{_on_off(enabled)}** にしました。"),
            ephemeral=True,
        )

    @settings_group.command(name="max_length", description="読み上げる最大文字数を設定します")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def max_length(self, interaction: discord.Interaction, length: app_commands.Range[int, 10, 1000]):
        await self.bot.db.set_guild_settings(interaction.guild_id, max_length=length)
        await interaction.response.send_message(
            view=ui.success("設定を変更しました", f"最大読み上げ文字数を **{length} 文字** にしました。"),
            ephemeral=True,
        )

    @settings_group.command(name="join_leave_notify", description="入退室時のアナウンス読み上げを切り替えます")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def join_leave_notify(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_settings(interaction.guild_id, notify_join_leave=int(enabled))
        await interaction.response.send_message(
            view=ui.success("設定を変更しました", f"入退室アナウンスを **{_on_off(enabled)}** にしました。"),
            ephemeral=True,
        )

    @settings_group.command(name="auto_join", description="誰かがボイスチャンネルに参加したときの自動接続を切り替えます")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def auto_join(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_settings(interaction.guild_id, auto_join=int(enabled))
        await interaction.response.send_message(
            view=ui.success(
                "設定を変更しました",
                f"VCへの自動接続を **{_on_off(enabled)}** にしました。",
                footer="接続したボイスチャンネルのチャット欄が、自動的に読み上げ対象になります。"
                if enabled
                else None,
            ),
            ephemeral=True,
        )

    @settings_group.command(name="auto_leave", description="ボイスチャンネルが無人になったときの自動退出を切り替えます")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def auto_leave(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_settings(interaction.guild_id, auto_leave_when_alone=int(enabled))
        await interaction.response.send_message(
            view=ui.success("設定を変更しました", f"無人時の自動退出を **{_on_off(enabled)}** にしました。"),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
