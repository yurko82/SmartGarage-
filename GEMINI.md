# Project Agent Rules & Execution Policy

## Autonomy & Command Execution Policy
- **Automatic Execution**: Execute all standard, non-destructive commands (such as reading files, grep/search, running tests, linting, building, starting/stopping local dev servers within the workspace, git status, git diff, editing project files) immediately without asking for user confirmation.
- **Critical & Dangerous Actions Confirmation**: ONLY pause and prompt the user for explicit confirmation before executing potentially destructive or critical actions, including:
  - Recursive file/directory deletion (`rm -rf`, deleting entire modules or root directories).
  - Force operations in Git (`git push --force`, `git reset --hard` that could drop uncommitted work).
  - Dropping databases or truncating production/critical data stores.
  - Modifying system-wide files outside the workspace (e.g. `/etc`, `/usr`, `/var`) or killing system critical processes.
  - Executing unknown or unverified external binary downloads (`curl ... | bash`).
