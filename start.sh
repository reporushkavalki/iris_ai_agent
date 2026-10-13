#!/usr/bin/env bash
# macOS / Linux launcher:  bash start.sh
set -e
cd "$(dirname "$0")"

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Iris needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "First start: setting things up (about a minute)..."
  "$PY" -m venv .venv
fi
if [ ! -f ".venv/.installed" ]; then
  echo "Installing the few packages Iris needs..."
  .venv/bin/python -m pip install --disable-pip-version-check --default-timeout 90 --retries 8 -r requirements.txt
  touch .venv/.installed
fi

exec .venv/bin/python app.py
