from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="このBOTの使い方を表示します")
    async def help_command(self, interaction: discord.Interaction):
        view = discord.ui.LayoutView()
        container = discord.ui.Container(accent_colour=discord.Colour.blurple())

        container.add_item(
            discord.ui.TextDisplay(
                "# 🗣️ 読み上げBOT ヘルプ\n"
                "VOICEVOXを使って、テキストチャンネルの発言をボイスチャンネルで読み上げます。"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "**基本操作**\n"
                "`/join` — ボイスチャンネルに接続し、使用したチャンネルを読み上げ対象にします\n"
                "`/leave` — 切断します\n"
                "`/skip` — 現在の読み上げをスキップします\n"
                "`/stopqueue` — 読み上げ待ちのメッセージをすべて破棄します\n"
                "`/read_here` — 読み上げ対象チャンネルをこのチャンネルに変更します"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "**ボイス設定**\n"
                "`/voice` — キャラクター・速度・音高・抑揚・音量を設定します（設定はユーザーごとに保存されます）"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "**読み上げ辞書**\n"
                "`/dictionary add` — 単語の読み方を登録（要: サーバー管理権限）\n"
                "`/dictionary remove` — 登録した単語を削除（要: サーバー管理権限）\n"
                "`/dictionary list` — 登録済み辞書の一覧を表示"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "**音声ファイル再生**\n"
                "`/sound play` — 音声ファイルをボイスチャンネルで再生（ループ・音量を指定可）\n"
                "`/sound stop` — 再生を停止\n"
                "`/sound volume` — 再生中の音量を変更\n"
                "`/sound status` — 再生状況を表示\n"
                "-# 再生中に読み上げが入ると、音声ファイルの音量が自動的に少し下がります。"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "**地震速報**\n"
                "`/earthquake enable` — 地震速報の通知をON/OFF\n"
                "`/earthquake channel` — 速報を投稿するチャンネルを指定\n"
                "`/earthquake min_scale` — 通知する震度のしきい値を設定\n"
                "`/earthquake test` — サンプルの速報で動作確認\n"
                "`/earthquake show` — 現在の設定を表示\n"
                "（変更には サーバー管理権限 が必要です）"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "**サーバー設定**\n"
                "`/settings show` — 現在の設定を表示\n"
                "`/settings read_name` / `max_length` / `join_leave_notify` / `auto_join` / `auto_leave`\n"
                "（変更には サーバー管理権限 が必要です）"
            )
        )

        view.add_item(container)
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
