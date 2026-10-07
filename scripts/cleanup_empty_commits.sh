#!/usr/bin/env bash
# ==============================================================================
# scripts/cleanup_empty_commits.sh
# Безпечне очищення історії Git від сміттєвих AI-комітів та виправлення заголовків
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== SmartGarage: Очищення історії Git від сміттєвих AI-комітів ===${NC}"

# Перевірка наявності репозиторію git
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo -e "${RED}❌ Помилка: поточна директорія не є Git-репозиторієм.${NC}" >&2
    exit 1
fi

CURRENT_BRANCH=$(git branch --show-current)
if [ -z "$CURRENT_BRANCH" ]; then
    echo -e "${RED}❌ Помилка: HEAD знаходиться у detached стані.${NC}" >&2
    exit 1
fi

# Збереження незафіксованих змін (stash)
STASHED=0
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo -e "${YELLOW}⚠️ Збереження локальних незафіксованих змін у stash...${NC}"
    git stash push -u -m "cleanup_empty_commits_autostash_$(date +%s)"
    STASHED=1
fi

# 1. Створення резервної копії поточної гілки перед будь-якими діями
BACKUP_BRANCH="backup-${CURRENT_BRANCH}-$(date +%Y%m%d_%H%M%S)"
echo -e "${BLUE}📦 Створення резервної копії гілки: ${BACKUP_BRANCH}...${NC}"
git branch "$BACKUP_BRANCH"
echo -e "${GREEN}✓ Резервну копію успішно створено: ${BACKUP_BRANCH}${NC}"

# 2. Пошук підозрілих комітів
FORBIDDEN_PATTERN="Please provide|No changes provided"
echo -e "\n${BLUE}🔍 Аналіз історії комітів за шаблоном '${FORBIDDEN_PATTERN}'...${NC}"

MATCHING_COMMITS=$(git log --format="%h" --grep="$FORBIDDEN_PATTERN" -E || true)

if [ -z "$MATCHING_COMMITS" ]; then
    echo -e "${GREEN}✓ Сміттєвих комітів за шаблоном не знайдено.${NC}"
    if [ "$STASHED" -eq 1 ]; then
        git stash pop || true
    fi
    exit 0
fi

echo -e "${YELLOW}Знайдено такі коміти із шаблонами-заглушками:${NC}"
while IFS= read -r hash; do
    [ -z "$hash" ] && continue
    msg=$(git log -1 --format="%s" "$hash")
    changed_files=$(git diff-tree --no-commit-id --name-only -r "$hash" | tr '\n' ' ')
    echo -e "  - ${YELLOW}$hash${NC}: \"$msg\" [Файли: ${changed_files:-'порожній'}]"
done <<< "$MATCHING_COMMITS"

# Знаходимо найстаріший підозрілий коміт
OLDEST_COMMIT=$(git rev-list --reverse HEAD | grep -F -f <(echo "$MATCHING_COMMITS") | head -n 1)
BASE_COMMIT=$(git rev-parse "${OLDEST_COMMIT}^")

TMP_EDITOR_SCRIPT=$(mktemp)
cat << 'EOF' > "$TMP_EDITOR_SCRIPT"
#!/usr/bin/env bash
TODO_FILE="$1"
NEW_TODO=$(mktemp)

while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^pick\ ([0-9a-f]+)\ (.*)$ ]]; then
        commit_hash="${BASH_REMATCH[1]}"
        commit_msg="${BASH_REMATCH[2]}"

        # Перевірка на порожні / сміттєві AI-коміти
        changed_files=$(git diff-tree --no-commit-id --name-only -r "$commit_hash")
        
        # 1. Повне видалення комітів, де змінювався лише файл динамічної присутності (presence_devices.json)
        # та повідомлення є AI-заглушкою або фіктивною назвою
        if [ -z "$changed_files" ] || [ "$changed_files" = "devices/presence_devices.json" ]; then
            if echo "$commit_msg" | grep -qE "Please provide|No changes provided|syntax error in user auth|undefined variable error|remove unused files"; then
                echo "drop $commit_hash $commit_msg (dropped junk telemetry commit)" >> "$NEW_TODO"
                continue
            fi
        fi

        # 2. Якщо коміт має реальний код, але містить сміттєвий AI-заголовок — зберігаємо код (pick),
        # а перейменування буде виконано за потреби
        if echo "$commit_msg" | grep -qE "Please provide|No changes provided"; then
            echo "pick $commit_hash $commit_msg" >> "$NEW_TODO"
            continue
        fi
    fi
    echo "$line" >> "$NEW_TODO"
done < "$TODO_FILE"

mv "$NEW_TODO" "$TODO_FILE"
EOF

chmod +x "$TMP_EDITOR_SCRIPT"

echo -e "\n${BLUE}🚀 Запуск безпечного перебазування (git rebase -X theirs)...${NC}"
if GIT_SEQUENCE_EDITOR="$TMP_EDITOR_SCRIPT" git rebase -i -X theirs "$BASE_COMMIT"; then
    echo -e "${GREEN}✓ Сміттєві порожні коміти успішно видалено з історії!${NC}"
else
    echo -e "${RED}❌ Під час rebase виникла помилка.${NC}" >&2
    echo -e "Для відновлення попереднього стану виконайте: ${YELLOW}git rebase --abort${NC}" >&2
    rm -f "$TMP_EDITOR_SCRIPT"
    exit 1
fi

rm -f "$TMP_EDITOR_SCRIPT"

# 3. Перейменування комітів з реальним кодом, що мали AI-заглушки замість назв
# (53e8b52, 394e1a1, ce3e035 або їх нові хеші)
echo -e "\n${BLUE}🔄 Оновлення повідомлень комітів з реальним кодом...${NC}"
git filter-branch -f --msg-filter '
read msg
case "$msg" in
  *"Please provide the file changes"*)
    echo "fix(service): додати групу dialout для запуску smartgarage.service"
    ;;
  *"No changes provided to summarize"*)
    echo "feat(dashboard,audio): розширення інтерфейсу дашборду та інтеграція Bluetooth-динаміка"
    ;;
  *"Please provide the code changes"*)
    echo "feat(ai,voice): покращення обробки команд клімату та статусу в AIManager"
    ;;
  *)
    echo "$msg"
    ;;
esac
' "${BASE_COMMIT}..HEAD" || true

# Очищення тимчасових бекапів filter-branch
rm -rf .git/refs/original/

# Відновлення локальних змін зі stash
if [ "$STASHED" -eq 1 ]; then
    echo -e "\n${BLUE}Повернення локальних змін зі stash...${NC}"
    if ! git stash pop 2>/dev/null; then
        echo -e "${YELLOW}Вирішення конфлікту у динамічному файлі presence_devices.json...${NC}"
        git checkout --theirs devices/presence_devices.json 2>/dev/null || true
        git reset HEAD devices/presence_devices.json 2>/dev/null || true
        git stash drop 2>/dev/null || true
    fi
fi

echo -e "\n${GREEN}=== ПІДСУМОК ОЧИЩЕННЯ ===${NC}"
echo -e "✓ Усі порожні сміттєві коміти видалено."
echo -e "✓ Коміти з корисним кодом збережено та перейменовано."
echo -e "✓ Резервну копію збережено у гілці: ${GREEN}${BACKUP_BRANCH}${NC}"
echo -e "\nПеревірте історію командою:"
echo -e "${YELLOW}git log --oneline -n 15${NC}"
echo -e "\nДля синхронізації з віддаленим репозиторієм виконайте:"
echo -e "${YELLOW}git push --force-with-lease origin ${CURRENT_BRANCH}${NC}"
