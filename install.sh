#!/usr/bin/env bash
# Installs one tagged release of odoo_cloud_tasks into a Claude cloud environment.
# Called by the environment's setup script (see setup-script-TEMPLATE.sh):
#   curl -fsSL "https://raw.githubusercontent.com/$REPO/$VERSION/install.sh" | bash -s -- "$REPO" "$VERSION"
# It needs no GitHub account: raw.githubusercontent.com serves public repositories to anyone.
set -euo pipefail

REPO="${1:?usage: install.sh OWNER/REPO TAG}"
VERSION="${2:?usage: install.sh OWNER/REPO TAG}"
BASE_URL="${ODOO_CLOUD_TASKS_BASE_URL:-https://raw.githubusercontent.com/$REPO/$VERSION}"
DEST="${ODOO_CLOUD_TASKS_DEST:-/opt/odoo_cloud_tasks}"
CLAUDE_DIR="$HOME/.claude"

# Every runtime file. tests/test_installer.py fails if this list and the repo disagree.
FILES=(
  scripts/odoo.py
  scripts/odoo_client/__init__.py
  scripts/odoo_client/cli.py
  scripts/odoo_client/client.py
  scripts/odoo_client/config.py
  scripts/odoo_client/errors.py
  scripts/odoo_client/json2.py
  scripts/odoo_client/jsonrpc.py
  scripts/odoo_client/normalize.py
  scripts/odoo_client/output.py
  scripts/odoo_client/periods.py
  scripts/odoo_client/safety.py
  scripts/odoo_client/transport.py
  .claude/skills/odoo/SKILL.md
  cloud/claude-settings.json
)

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT

for file in "${FILES[@]}"; do
  mkdir -p "$staging/$(dirname "$file")"
  curl -fsSL --retry 3 "$BASE_URL/$file" -o "$staging/$file"
done
python3 "$staging/scripts/odoo.py" --version >/dev/null

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -R "$staging" "$DEST"
chmod -R a+rX "$DEST"

# Claude Code loads ~/.claude/CLAUDE.md in every session: the skill's instructions, with the install path.
mkdir -p "$CLAUDE_DIR"
{
  printf '<!-- odoo_cloud_tasks %s, written by install.sh -->\n\n' "$VERSION"
  awk 'NR == 1 && $0 == "---" { fm = 1; next } fm && $0 == "---" { fm = 0; next } !fm' \
    "$DEST/.claude/skills/odoo/SKILL.md" \
    | sed "s#python3 scripts/odoo.py#python3 $DEST/scripts/odoo.py#g"
} > "$CLAUDE_DIR/CLAUDE.md"

python3 - "$DEST/cloud/claude-settings.json" "$CLAUDE_DIR/settings.json" "$DEST" <<'PY'
import json
import os
import sys

source, target, dest = sys.argv[1:4]
with open(source, encoding="utf-8") as handle:
    ours = json.loads(handle.read().replace("{{DEST}}", dest))
current = {}
if os.path.exists(target):
    with open(target, encoding="utf-8") as handle:
        current = json.load(handle)
permissions = current.setdefault("permissions", {})
for kind in ("allow", "deny"):
    rules = permissions.setdefault(kind, [])
    for rule in ours["permissions"][kind]:
        if rule not in rules:
            rules.append(rule)
with open(target, "w", encoding="utf-8") as handle:
    json.dump(current, handle, indent=2)
    handle.write("\n")
PY

echo "odoo_cloud_tasks $VERSION installed in $DEST"
