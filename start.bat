@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

if exist ".venv\Scripts\python.exe" goto install

set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1 && set "PY=python"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if defined PY goto venv

echo Python 3.10 以上が見つかりません。winget でインストールします...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
    goto venv
)
echo Python をインストールできませんでした。
echo https://www.python.org/downloads/ からインストールして、もう一度 start.bat を実行してください。
pause
exit /b 1

:venv
echo Python の仮想環境を作成しています...
%PY% -m venv .venv
if errorlevel 1 (
    echo 仮想環境の作成に失敗しました。
    pause
    exit /b 1
)

:install
fc /b requirements.txt .venv\requirements.installed >nul 2>&1
if not errorlevel 1 goto run
echo 依存パッケージをインストールしています...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo 依存パッケージのインストールに失敗しました。
    pause
    exit /b 1
)
copy /y requirements.txt .venv\requirements.installed >nul

:run
".venv\Scripts\python.exe" launcher.py
if errorlevel 1 pause
