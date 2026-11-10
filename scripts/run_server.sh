#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${VENV_PYTHON:-$HOME/AI/OpenInterpreter/venv/bin/python}"
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON="python3"
fi

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

exec "$VENV_PYTHON" -m server.webapp
