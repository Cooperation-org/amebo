#!/usr/bin/env bash
#
# Deploy the amebo frontend on VM 200 (systemd + in-place Next.js build).
#
# Build and restart are ONE operation. `next start` serves the chunk filenames
# it read at startup; a build replaces those files, so a build without a restart
# leaves every page returning 200 with its CSS and JS 500ing — the app renders a
# spinner forever. That is what broke amebo.linkedtrust.us on 2026-08-06.
#
#   ./scripts/deploy-frontend.sh          pull, build, restart, verify
#   ./scripts/deploy-frontend.sh --check   verify only (no build, no restart)
#
# NOTE: the Docker-based ./deploy.sh at the repo root does NOT apply to VM 200.
#
set -euo pipefail

REPO=/opt/shared/repos/amebo
FRONTEND="$REPO/frontend"
SERVICE=amebo-frontend
URL=https://amebo.linkedtrust.us
CHECK_PATH=/dashboard/list

red()  { printf '\033[0;31m%s\033[0m\n' "$*"; }
green(){ printf '\033[0;32m%s\033[0m\n' "$*"; }
info() { printf 'ℹ %s\n' "$*"; }

disk_build_id() { cat "$FRONTEND/.next/BUILD_ID"; }
served_build_id() { curl -sS -m 20 "$URL$CHECK_PATH" | grep -oE '\\"b\\":\\"[^\\]*' | head -1 | sed 's/.*"//'; }

# The real test: does every asset the served page references actually exist?
verify() {
  local disk served html failed=0
  disk=$(disk_build_id)
  html=$(curl -sS -m 20 "$URL$CHECK_PATH")
  served=$(printf '%s' "$html" | grep -oE '\\"b\\":\\"[^\\]*' | head -1 | sed 's/.*"//')

  if [ "$disk" != "$served" ]; then
    red "✗ build drift: disk=$disk served=$served"
    red "  the running process is serving a build that is no longer on disk."
    red "  fix: sudo systemctl restart $SERVICE"
    return 1
  fi

  while read -r asset; do
    local code
    code=$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "$URL$asset")
    if [ "$code" != "200" ]; then
      red "✗ $asset -> $code"
      failed=1
    fi
  done < <(printf '%s' "$html" | grep -oE '/_next/static/[^"]+\.(js|css)' | sort -u)

  [ "$failed" -eq 0 ] || { red "✗ page references assets that are not being served"; return 1; }
  green "✓ build $served serving cleanly, all assets 200"
}

if [ "${1:-}" = "--check" ]; then
  verify
  exit $?
fi

cd "$FRONTEND"

info "pulling $REPO"
git -C "$REPO" pull --ff-only

# Reinstall only when the lockfile actually changed since the last deploy.
LOCK_STAMP="$FRONTEND/.next/.deployed-lock-sha"
lock_sha=$(sha256sum package-lock.json | cut -d' ' -f1)
if [ "$(cat "$LOCK_STAMP" 2>/dev/null || true)" != "$lock_sha" ]; then
  info "package-lock.json changed — npm ci"
  npm ci
fi

info "building $(git -C "$REPO" log -1 --format='%h %s')"
NODE_ENV=production npm run build

info "restarting $SERVICE"
sudo systemctl restart "$SERVICE"
printf '%s\n' "$lock_sha" > "$LOCK_STAMP"

# next start needs a moment before it answers.
for _ in $(seq 1 20); do
  sleep 2
  [ "$(served_build_id 2>/dev/null || true)" = "$(disk_build_id)" ] && break
done

verify
