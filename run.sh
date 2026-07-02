#!/usr/bin/env bash
# One-command start for the CCR Platform (macOS/Linux).
# First run creates a virtualenv, installs dependencies, and downloads the
# default embedding model (~90 MB) on first analysis.
set -euo pipefail
cd "$(dirname "$0")/backend"

if [ ! -d .venv ]; then
  echo "==> Creating virtualenv (.venv)…"
  python3 -m venv .venv
fi
source .venv/bin/activate

echo "==> Installing dependencies (first run may take a few minutes)…"
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo ""
echo "==> CCR Platform running at:  http://127.0.0.1:8000"
echo "    (Ctrl+C to stop)"
echo ""
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
