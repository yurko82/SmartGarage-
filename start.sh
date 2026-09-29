#!/usr/bin/env bash
# ==============================================================================
# Smart Garage - Open Interpreter Entrypoint
# Migrated to local Qwen 2.5 Coder 7B with Docker Isolation
# ==============================================================================
cd "$(dirname "$0")" || exit 1

exec ./scripts/run_interpreter.sh "$@"
