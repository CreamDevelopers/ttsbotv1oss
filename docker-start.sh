#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || cp .env.example .env

if ! grep -qE '^DISCORD_TOKEN=.+' .env; then
    echo "Discord Developer Portal で発行した BOT のトークンを貼り付けてください。"
    read -rp "DISCORD_TOKEN: " token
    if grep -q '^DISCORD_TOKEN=' .env; then
        sed -i "s|^DISCORD_TOKEN=.*|DISCORD_TOKEN=${token}|" .env
    else
        echo "DISCORD_TOKEN=${token}" >> .env
    fi
fi

docker compose up -d --build
echo "起動しました。ログは Ctrl+C で抜けられます（BOT は動き続けます）。"
docker compose logs -f bot
