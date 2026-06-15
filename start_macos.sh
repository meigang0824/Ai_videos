#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 $PYTHON_BIN，请先安装 Python 3.11+，或用 PYTHON_BIN=/path/to/python 指定。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

if [ ! -d "app_ui/node_modules" ]; then
  npm --prefix app_ui install
fi
npm --prefix app_ui run build

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8010}"
echo "启动 CosyVoice API Only: http://127.0.0.1:${PORT}"
python -m uvicorn api_server:app --host "$HOST" --port "$PORT"
