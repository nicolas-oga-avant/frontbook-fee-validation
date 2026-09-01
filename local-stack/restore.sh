#!/usr/bin/env bash
# Restore the untracked overrides that make the local basic + CCAPI + CRM stack work.
#
# They live in the repo checkouts and only in .git/info/exclude, so a `git clean -xfd` in any of
# them deletes the lot. This puts them back and re-excludes them. Safe to re-run.
#
#   ./restore.sh            # restore files, then print how to bring the stack up
#   ./restore.sh --up       # restore and start all three stacks
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Where the sibling repo checkouts live. Override on a machine that lays them out differently:
#   AVANT_ROOT=/path/to/checkouts ./restore.sh
ROOT="${AVANT_ROOT:-$(cd "$HERE/../../.." && pwd)}"

for repo in avant-basic credit-card-api crm; do
  [ -d "$ROOT/$repo" ] && continue
  echo "FATAL: $repo not found under $ROOT" >&2
  echo "Set AVANT_ROOT to the directory holding the repo checkouts, e.g." >&2
  echo "  AVANT_ROOT=~/Source/avant $0 ${*:-}" >&2
  exit 1
done

restore() {  # $1=source in this dir  $2=repo  $3=path within the repo
  local src="$HERE/$1" repo="$ROOT/$2" rel="$3"
  if [ ! -d "$repo" ]; then
    echo "  SKIP  $2 not found at $repo"
    return
  fi
  mkdir -p "$(dirname "$repo/$rel")"
  cp "$src" "$repo/$rel"
  # Never let these get committed: the checkouts are shared with other agent sessions.
  local ex="$repo/.git/info/exclude"
  if [ -f "$ex" ] && ! grep -qxF "$rel" "$ex"; then
    echo "$rel" >> "$ex"
  fi
  echo "  ok    $2/$rel"
}

echo "Restoring local-stack overrides into $ROOT"
restore avant-basic.docker-compose.override.yml  avant-basic     docker-compose.override.yml
restore zzz_local_transunion_mock.rb             avant-basic     config/initializers/zzz_local_transunion_mock.rb
restore zzz_local_cma_stub.rb                    avant-basic     config/initializers/zzz_local_cma_stub.rb
restore credit-card-api.compose.override.yml     credit-card-api compose.override.yml
restore crm.docker-compose.override.yml          crm             docker-compose.override.yml

echo
echo "Verifying nothing became git-visible:"
for r in avant-basic credit-card-api crm; do
  [ -d "$ROOT/$r" ] || continue
  n="$(cd "$ROOT/$r" && git status --porcelain 2>/dev/null | grep -cE 'override\.yml|zzz_local_' || true)"
  echo "  $r: $n tracked-visible override files (expect 0)"
done

if [ "${1:-}" = "--up" ]; then
  echo
  echo "Starting stacks..."
  (cd "$ROOT/avant-basic"     && docker compose -p basic-csrv-5300 up -d web sidekiq)
  (cd "$ROOT/credit-card-api" && docker compose -p ccapi-csrv-5300 up -d web sidekiq)
  (cd "$ROOT/crm"             && docker compose -p crm-csrv-5300  up -d web)
  echo
  echo "Waiting for basic (first boot restores a large DB dump, several minutes)..."
  until [ "$(curl -s -m 8 -o /dev/null -w '%{http_code}' http://localhost:5001/ 2>/dev/null)" = "200" ]; do sleep 10; done
  echo "  basic  ready on :5001"
  # The CRM client bundle lives in the container's writable layer, so any recreate loses it and
  # every request 500s on `Failed to lookup view "login.ejs"`.
  echo "Building the CRM client bundle (required after any recreate, ~53s)..."
  (cd "$ROOT/crm" && docker compose -p crm-csrv-5300 exec -T web sh -c 'cd /app && yarn webpack' >/dev/null)
  echo "  crm    ready on :4000"
  echo "  ccapi  on :7100"
else
  cat <<'EOF'

Now bring the stacks up (or re-run with --up):

  cd ~/Source/avant/avant-basic     && docker compose -p basic-csrv-5300 up -d web sidekiq
  cd ~/Source/avant/credit-card-api && docker compose -p ccapi-csrv-5300 up -d web sidekiq
  cd ~/Source/avant/crm             && docker compose -p crm-csrv-5300  up -d web
  cd ~/Source/avant/crm && docker compose -p crm-csrv-5300 exec web sh -c 'cd /app && yarn webpack'

basic :5001   ccapi :7100   CSP :4000/us/
EOF
fi
