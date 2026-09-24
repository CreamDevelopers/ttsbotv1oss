from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core import ui

log = logging.getLogger("tts.cog.dictionary")


class DictionaryCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    dictionary_group = app_commands.Group(
        name="dictionary", description="読み上げ辞書の管理", guild_only=True
    )

    @dictionary_group.command(name="add", description="単語の読み方を登録します")
    @app_commands.describe(word="登録する単語（そのまま置換対象になります）", reading="読み方（ひらがな/カタカナ推奨）")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, word: str, reading: str):
        await self.bot.db.add_dictionary_entry(interaction.guild_id, word, reading)
        await interaction.response.send_message(
            view=ui.success(
                "辞書に登録しました",
                ui.field_lines([("単語", word), ("読み方", reading)]),
                footer="このサーバーの読み上げにだけ適用されます。",
            ),
            ephemeral=True,
        )

    @dictionary_group.command(name="remove", description="登録した単語を削除します")
    @app_commands.describe(word="削除する単語")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, word: str):
        removed = await self.bot.db.remove_dictionary_entry(interaction.guild_id, word)
        if removed:
            await interaction.response.send_message(
                view=ui.success("辞書から削除しました", f"「{word}」の登録を取り消しました。"), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                view=ui.warning("登録されていません", f"「{word}」は辞書にありません。"), ephemeral=True
            )

    @dictionary_group.command(name="list", description="登録されている辞書の一覧を表示します")
    async def list_(self, interaction: discord.Interaction):
        entries = await self.bot.db.get_dictionary(interaction.guild_id)
        if not entries:
            await interaction.response.send_message(
                view=ui.notice(
                    "辞書は空です",
                    "`/dictionary add` で単語の読み方を登録できます。",
                    emoji="📖",
                ),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            view=ui.notice(
                "このサーバーの辞書",
                ui.field_lines(entries),
                emoji="📖",
                footer=f"全 {len(entries)} 件",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(DictionaryCog(bot))
