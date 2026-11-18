#!/bin/bash
# Setup script for one client's Claude cloud environment
# (claude.ai/code → environment settings → Setup script).
#
# 1. Set REPO to your public GitHub repository and VERSION to a release tag.
# 2. Paste the client's company notes between the COMPANY_NOTES lines.
# 3. Keep the filled-in copy OUTSIDE this repository: the notes are client-specific.
#
# To upgrade the client later, change VERSION; the environment rebuilds on its next run.
set -euo pipefail

REPO="<github-owner>/odoo_cloud_tasks"
VERSION="v1.0.0"

curl -fsSL "https://raw.githubusercontent.com/$REPO/$VERSION/install.sh" | bash -s -- "$REPO" "$VERSION"

cat >> ~/.claude/CLAUDE.md <<'COMPANY_NOTES'

# Company notes
<paste the client's company notes here; see company-notes-TEMPLATE.md>
COMPANY_NOTES
