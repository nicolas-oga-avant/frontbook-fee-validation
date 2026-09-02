#!/usr/bin/env bash
# Bring a machine from nothing to a stack that can run one frontbook fee validation Run.
#
#   ./bootstrap.sh            # set up and verify
#   ./bootstrap.sh --verify   # verify only, change nothing
#
# Idempotent. Safe to re-run. Every step verifies rather than assuming, because nearly
# every failure mode in this stack is silent.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$HERE/../../.." && pwd)"          # the repo root
VALIDATION_ROOT="${VALIDATION_ROOT:-$HOME/Source/avant/frontbook-validation}"
REPOS=(avant-basic credit-card-api crm)
VERIFY_ONLY="${1:-}"

ok()   { printf '  ok    %s\n' "$*"; }
info() { printf '  ..    %s\n' "$*"; }
die()  { printf '\nFATAL: %s\n' "$*" >&2; exit 1; }

step() { printf '\n== %s\n' "$*"; }

# --- 1. prerequisites ------------------------------------------------------------------
step "Prerequisites"
for c in git docker python3; do
  command -v "$c" >/dev/null || die "$c is not installed"
  ok "$c"
done
docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker/OrbStack and re-run."
ok "docker daemon"
info "TemplateFlow key comes from .env.local - see below"

# Compose project names are fixed, so a stack already running from a DIFFERENT directory
# will be recreated against $VALIDATION_ROOT. The database itself survives - it lives on the
# named volume <project>_ab_postgres16_data, which is keyed to the project name rather than
# the working directory, so `down` (without -v) keeps it and the next `up` reattaches it.
# What does break is the schema: the new checkout can sit at a different SHA than the one
# those migrations ran under. Refuse rather than silently reshape someone's in-progress run.
running_dir="$(docker inspect basic-frontbook-fee-validation-web-1 \
  --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null || true)"
if [ -n "$running_dir" ] && [ "$running_dir" != "$VALIDATION_ROOT/avant-basic" ]; then
  die "a basic-frontbook-fee-validation stack is already running from:
    $running_dir
  but this bootstrap targets:
    $VALIDATION_ROOT/avant-basic
  Continuing would recreate those containers against a different checkout. The database
  survives on its named volume, but it would then be serving a checkout it was never
  migrated for. Either set VALIDATION_ROOT to the directory above, or stop the other
  stack first:
    docker compose -p basic-frontbook-fee-validation down
  (\`down\` keeps the volume; only \`down -v\` destroys the data.)"
fi


# --- 2. checkouts ----------------------------------------------------------------------
step "Checkouts under $VALIDATION_ROOT"
[ "$VERIFY_ONLY" = "--verify" ] || mkdir -p "$VALIDATION_ROOT"
for r in "${REPOS[@]}"; do
  dest="$VALIDATION_ROOT/$r"
  if [ -d "$dest/.git" ] || [ -f "$dest/.git" ]; then
    ok "$r present"
    continue
  fi
  [ "$VERIFY_ONLY" = "--verify" ] && die "$r missing at $dest"
  existing="$HOME/Source/avant/$r"
  if [ -d "$existing/.git" ]; then
    # A worktree off an existing clone: no second full fetch, and it cannot be moved
    # onto another branch by another session.
    info "$r: adding worktree from $existing"
    git -C "$existing" fetch --quiet origin main
    git -C "$existing" worktree add --quiet "$dest" origin/main
  else
    info "$r: cloning (this takes a while for avant-basic)"
    git clone --quiet "git@github.com:AvantFinCo/$r.git" "$dest"
    git -C "$dest" checkout --quiet main
  fi
  ok "$r ready"
done

# main, not mp: this validates what ships to production. See CLAUDE.md.
for r in "${REPOS[@]}"; do
  sha="$(git -C "$VALIDATION_ROOT/$r" rev-parse --short HEAD)"
  ok "$r @ $sha"
done

# --- 3. credentials --------------------------------------------------------------------
step "Credentials"
ENVFILE="$WORKDIR/.env.local"
if [ ! -f "$ENVFILE" ]; then
  [ "$VERIFY_ONLY" = "--verify" ] && die ".env.local missing"
  cp "$WORKDIR/.env.local.example" "$ENVFILE"; chmod 600 "$ENVFILE"
  info "created $ENVFILE from the example"
fi
set -a; . "$ENVFILE"; set +a

if [ -z "${AVANT_TEMPLATES_API_KEY:-}" ]; then
  if [ "$VERIFY_ONLY" != "--verify" ] && [ -n "${TEMPLATEFLOW_KEY_FROM:-}" ]; then
    info "reading the key from \$TEMPLATEFLOW_KEY_FROM"
    key="$(cat "$TEMPLATEFLOW_KEY_FROM" 2>/dev/null || true)"
    if [ -n "$key" ]; then
      # macOS and GNU sed disagree on -i; write via a temp file instead.
      awk -v k="$key" '/^AVANT_TEMPLATES_API_KEY=/{print "AVANT_TEMPLATES_API_KEY=" k; next} {print}' \
        "$ENVFILE" > "$ENVFILE.tmp" && mv "$ENVFILE.tmp" "$ENVFILE" && chmod 600 "$ENVFILE"
      export AVANT_TEMPLATES_API_KEY="$key"
      ok "key read from the pod and stored"
    fi
  fi
fi
[ -n "${AVANT_TEMPLATES_API_KEY:-}" ] || die "AVANT_TEMPLATES_API_KEY is empty in $ENVFILE.
  Every render will fail with 401, long after the stack looks healthy.
  This is the PRODUCTION TemplateFlow key - ask a teammate to send you their .env.local.
  Renders go out in preview mode and persist nothing (docs/adr/0002), but the credential
  is real: keep it out of commits."
ok "AVANT_TEMPLATES_API_KEY set (${#AVANT_TEMPLATES_API_KEY} chars)"
ok "AVANT_TEMPLATES_HOST=${AVANT_TEMPLATES_HOST:-unset}"

# --- 4. patches ------------------------------------------------------------------------
step "Local patches"
if [ "$VERIFY_ONLY" = "--verify" ]; then
  for f in docker-compose.override.yml \
           config/initializers/zzz_local_transunion_mock.rb \
           config/initializers/zzz_local_cma_stub.rb \
           config/initializers/zzz_local_consolidated_cma.rb; do
    [ -f "$VALIDATION_ROOT/avant-basic/$f" ] || die "missing patch: avant-basic/$f"
  done
  ok "patches present"
else
  AVANT_ROOT="$VALIDATION_ROOT" "$WORKDIR/local-stack/restore.sh" | sed 's/^/  /'
fi

# --- 5. stack --------------------------------------------------------------------------
step "Stack"
if [ "$VERIFY_ONLY" != "--verify" ]; then
  (cd "$VALIDATION_ROOT/avant-basic"     && docker compose -p basic-frontbook-fee-validation up -d web sidekiq >/dev/null)
  (cd "$VALIDATION_ROOT/credit-card-api" && docker compose -p ccapi-frontbook-fee-validation up -d web sidekiq >/dev/null)
  (cd "$VALIDATION_ROOT/crm"             && docker compose -p crm-frontbook-fee-validation  up -d web >/dev/null)
  info "waiting for basic (first boot restores a large DB dump - can be several minutes)"
fi

for i in $(seq 1 60); do
  code="$(curl -s -o /dev/null -m 25 -w '%{http_code}' http://localhost:5001/ 2>/dev/null || true)"
  [ "$code" = "200" ] && break
  sleep 10
done
[ "${code:-}" = "200" ] || die "basic never returned 200 on :5001 (last: ${code:-none}).
  Check: docker compose -p basic-frontbook-fee-validation logs --tail=50 web"
ok "basic :5001"

curl -s -o /dev/null -m 20 http://localhost:7100/ 2>/dev/null && ok "ccapi :7100" \
  || die "ccapi not answering on :7100"

# The CRM client bundle lives in the container's writable layer, so any recreate loses it
# and every request 500s on `Failed to lookup view "login.ejs"`.
if [ "$VERIFY_ONLY" != "--verify" ]; then
  info "building the CRM client bundle (~53s, required after any recreate)"
  (cd "$VALIDATION_ROOT/crm" && docker compose -p crm-frontbook-fee-validation exec -T web sh -c 'cd /app && yarn webpack' >/dev/null 2>&1) || true
fi
crm_body="$(curl -s -m 20 http://localhost:4000/us/ 2>/dev/null || true)"
case "$crm_body" in
  *login.ejs*) die "CRM is serving the login.ejs error - the client bundle is missing.
  Run: cd $VALIDATION_ROOT/crm && docker compose -p crm-frontbook-fee-validation exec web sh -c 'cd /app && yarn webpack'" ;;
  *) ok "crm :4000" ;;
esac

# --- 6. the things that fail silently --------------------------------------------------
step "Silent-failure checks"
mocks="$(cd "$VALIDATION_ROOT/avant-basic" && docker compose -p basic-frontbook-fee-validation exec -T web \
  sh -c 'printenv ENABLE_MOCK_SERVICES; printenv MOCK_TRANSUNION' 2>/dev/null | tr -d '\r' | paste -sd, -)"
[ "$mocks" = "1,1" ] || die "mock env vars are '$mocks', expected '1,1'.
  Without them the TransUnion mock never registers and EVERY application declines with
  missing_transunion_report, with no mention of mocks anywhere."
ok "ENABLE_MOCK_SERVICES + MOCK_TRANSUNION"

tf="$(cd "$VALIDATION_ROOT/avant-basic" && docker compose -p basic-frontbook-fee-validation exec -T web \
  sh -c 'printenv AVANT_TEMPLATES_API_KEY | wc -c' 2>/dev/null | tr -d ' \r')"
[ "${tf:-1}" -gt 1 ] || die "AVANT_TEMPLATES_API_KEY did not reach the container.
  Env is baked at container creation. Re-run:
    cd $VALIDATION_ROOT/avant-basic && docker compose -p basic-frontbook-fee-validation up -d --force-recreate web sidekiq
  Never --force-recreate CRM: it wipes the client bundle."
ok "TemplateFlow key reached the container"

# An initializer that exists on disk has told you nothing about whether it RAN. Both of these
# log a [local] line at boot; assert on the log, not the file. Note the destination: Rails logs
# to log/development.log INSIDE the container, so `docker compose logs` shows none of this.
for want in 'LocalConsolidatedCma active' 'FakeTransunion mock registered'; do
  (cd "$VALIDATION_ROOT/avant-basic" && docker compose -p basic-frontbook-fee-validation exec -T web \
    sh -c 'grep -h "\[local\]" log/development.log 2>/dev/null' 2>/dev/null) | grep -qF "$want" \
    || die "no '[local] $want' in log/development.log.
  The initializer did not run, so the behaviour it provides is silently absent. Check that
  local-stack/restore.sh put it in config/initializers/ and that the container was recreated."
  ok "boot log: $want"
done

http="$(curl -s -o /dev/null -m 25 -w '%{http_code}' \
  -H "Api-Key: $AVANT_TEMPLATES_API_KEY" "https://$AVANT_TEMPLATES_HOST/api/v1/templates" || true)"
[ "$http" = "200" ] || die "TemplateFlow returned $http for the templates list.
  401 means the key is wrong. Take STAGING_API_KEY, not API_KEY."
ok "TemplateFlow reachable and the key is accepted"

printf '\nReady. basic :5001   ccapi :7100   CSP :4000/us/\n'
printf 'Checkouts: %s\n' "$VALIDATION_ROOT"
