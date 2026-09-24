#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

need=()
if ! command -v python3 >/dev/null 2>&1; then
    need+=(python3 python3-venv)
elif ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 3.10 以上が必要です（現在: $(python3 --version)）"
    exit 1
elif ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    need+=(python3-venv)
fi
command -v ffmpeg >/dev/null 2>&1 || need+=(ffmpeg)
ldconfig -p 2>/dev/null | grep -q 'libopus\.so' || need+=(libopus0)

if [ ${#need[@]} -gt 0 ]; then
    echo "必要なパッケージをインストールします: ${need[*]}"
    sudo=""
    [ "$(id -u)" -ne 0 ] && sudo="sudo"
    $sudo apt-get update
    $sudo apt-get install -y "${need[@]}"
fi

if [ ! -x .venv/bin/python ]; then
    echo "Python の仮想環境を作成しています..."
    python3 -m venv .venv
fi

if ! cmp -s requirements.txt .venv/requirements.installed; then
    echo "依存パッケージをインストールしています..."
    .venv/bin/python -m pip install --upgrade pip -q
    .venv/bin/python -m pip install -r requirements.txt -q
    cp requirements.txt .venv/requirements.installed
fi

exec .venv/bin/python launcher.py
