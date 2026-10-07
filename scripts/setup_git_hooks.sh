#!/usr/bin/env bash
# ==============================================================================
# scripts/setup_git_hooks.sh
# Встановлення git хуків для SmartGarage
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🔧 Налаштування Git хуків у репозиторії..."

# Варіант 1: Копіювання в .git/hooks
mkdir -p "$REPO_ROOT/.git/hooks"
chmod +x "$SCRIPT_DIR/hooks/pre-commit" "$SCRIPT_DIR/hooks/commit-msg"
cp "$SCRIPT_DIR/hooks/pre-commit" "$REPO_ROOT/.git/hooks/pre-commit"
cp "$SCRIPT_DIR/hooks/commit-msg" "$REPO_ROOT/.git/hooks/commit-msg"

echo "✅ Git хуки pre-commit та commit-msg успішно встановлено та активовано!"
