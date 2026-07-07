#!/usr/bin/env bash
# push_data.sh
# ------------
# Option B from DEV-HANDOFF-network-issue.md: run this on a cron schedule on any
# internal server that can reach metabase.ops.tutenlabs.com. It pulls the repo,
# runs update_data.py to fetch yesterday's calls, and pushes the updated data.json
# straight to GitHub -- no GitHub Actions involved, so the network-reachability
# problem with GitHub's hosted runners doesn't apply.
#
# Fill in the four placeholders below, then test with: bash push_data.sh
# Once it works, add it to crontab, e.g.:
#   10 6 * * * /path/to/push_data.sh >> /var/log/call-dashboard-update.log 2>&1

set -euo pipefail

# ---- fill these in ----
REPO_URL="https://github.com/Tutenlabs95/Call-Dashboard.git"
GITHUB_PAT="REPLACE_WITH_FINE_GRAINED_PAT"       # repo-scoped, Contents: Read and write
export METABASE_URL="https://metabase.ops.tutenlabs.com"
export METABASE_USER="REPLACE_WITH_METABASE_LOGIN_EMAIL"
export METABASE_PASSWORD="REPLACE_WITH_METABASE_PASSWORD"
# ------------------------

WORKDIR="${WORKDIR:-$HOME/.call-dashboard-sync}"
AUTHED_URL="${REPO_URL/https:\/\//https:\/\/x-access-token:${GITHUB_PAT}@}"

if [ ! -d "$WORKDIR/.git" ]; then
  echo "Cloning repo into $WORKDIR..."
  git clone "$AUTHED_URL" "$WORKDIR"
else
  echo "Repo already present at $WORKDIR, pulling latest..."
  git -C "$WORKDIR" remote set-url origin "$AUTHED_URL"
  git -C "$WORKDIR" pull --ff-only
fi

cd "$WORKDIR"

python3 -m pip install --quiet requests

echo "Running update_data.py..."
python3 update_data.py

git config user.name "dashboard-sync-bot"
git config user.email "dashboard-sync-bot@local"

if git diff --quiet -- data.json; then
  echo "No changes to data.json (day may already be recorded, or no calls found). Nothing to push."
else
  git add data.json
  git commit -m "Daily data update: $(date -u +%Y-%m-%d)"
  git push origin HEAD:main
  echo "Pushed updated data.json."
fi
