@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
    echo Docker が見つかりません。Docker Desktop をインストールしてから実行してください。
    pause
    exit /b 1
)

if not exist .env copy .env.example .env >nul
findstr /r /c:"^DISCORD_TOKEN=..*" .env >nul
if errorlevel 1 (
    echo Discord Developer Portal で発行した BOT のトークンを貼り付けてください。
    set /p "TOKEN=DISCORD_TOKEN: "
    call :settoken
)

docker compose up -d --build
if errorlevel 1 (
    pause
    exit /b 1
)
echo 起動しました。このウィンドウを閉じても BOT は動き続けます。
docker compose logs -f bot
exit /b 0

:settoken
powershell -NoProfile -Command "$p='.env'; $t=$env:TOKEN; $c=@(Get-Content $p -Encoding UTF8 | Where-Object { $_ -notmatch '^DISCORD_TOKEN=' }); $c += 'DISCORD_TOKEN=' + $t; Set-Content $p $c -Encoding UTF8"
exit /b 0
