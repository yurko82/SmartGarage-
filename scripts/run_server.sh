#!/usr/bin/env bash
set -e

PROJECT_DIR="/home/yurko/AI/SmartGarage"
VENV_PYTHON="/home/yurko/AI/OpenInterpreter/venv/bin/python"

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"

exec "$VENV_PYTHON" -m server.webapp
