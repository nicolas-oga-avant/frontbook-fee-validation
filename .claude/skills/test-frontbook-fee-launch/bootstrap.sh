#!/usr/bin/env bash
# Bring a machine from nothing to a stack that can run one frontbook fee validation Run.
#
#   ./bootstrap.sh                    # set up and verify, against main
#   ./bootstrap.sh --verify           # verify only, change nothing
#   ./bootstrap.sh --branch mp        # set up and verify, against mp
#
# The branch is a parameter because the fee launch may ship before, after or alongside MP.
# A branch other than main gets its own checkout root, its own Compose projects and its own
# database volume, so the two do not overwrite each other. `main` keeps the original names.
#
# Idempotent. Safe to re-run. Every step verifies rather than assuming, because nearly
# every failure mode in this stack is silent.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$(cd "$HERE/../../.." && pwd)"          # the repo root
REPOS=(avant-basic credit-card-api crm)

VERIFY_ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --verify) VERIFY_ONLY="--verify"; shift ;;
    --branch) VALIDATION_BRANCH="${2:?--branch needs a branch name}"; shift 2 ;;
    --branch=*) VALIDATION_BRANCH="${1#--branch=}"; shift ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

. "$WORKDIR/local-stack/branch-env.sh"
VALIDATION_ROOT="${VALIDATION_ROOT:-$DEFAULT_VALIDATION_ROOT}"

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
ok "branch under test: $VALIDATION_BRANCH  (compose project: $BASIC_PROJECT)"
info "TemplateFlow key comes from .env.local - see below"

# Compose project names are fixed, so a stack already running from a DIFFERENT directory
# will be recreated against $VALIDATION_ROOT. The database itself survives - it lives on the
# named volume <project>_ab_postgres16_data, which is keyed to the project name rather than
# the working directory, so `down` (without -v) keeps it and the next `up` reattaches it.
# What does break is the schema: the new checkout can sit at a different SHA than the one
# those migrations ran under. Refuse rather than silently reshape someone's in-progress run.
running_dir="$(docker inspect ${BASIC_PROJECT}-web-1 \
  --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' 2>/dev/null || true)"
if [ -n "$running_dir" ] && [ "$running_dir" != "$VALIDATION_ROOT/avant-basic" ]; then
  die "a $BASIC_PROJECT stack is already running from:
    $running_dir
  but this bootstrap targets:
    $VALIDATION_ROOT/avant-basic
  Continuing would recreate those containers against a different checkout. The database
  survives on its named volume, but it would then be serving a checkout it was never
  migrated for. Either set VALIDATION_ROOT to the directory above, or stop the other
  stack first:
    docker compose -p "$BASIC_PROJECT" down
  (\`down\` keeps the volume; only \`down -v\` destroys the data.)"
fi

# A different branch's stack binds the same host ports (5001/7100/4000), so it does not
# collide by name - it collides by port, and Compose reports that as an opaque bind failure.
# This also has to fire under --verify, harmless as that sounds: every health check below is
# a curl at localhost, so verifying `mp` while `main` holds :5001 passes green against the
# wrong branch entirely.
# Filtered with `case`, not `grep -v 'a\|b'`: macOS grep is BSD, where `\|` is not an
# alternation but a literal, so that form excludes nothing and every stack reads as foreign.
other=""
for proj in $(docker ps --filter 'name=-frontbook-fee-validation' --format '{{.Labels}}' 2>/dev/null \
  | tr ',' '\n' | sed -n 's/^com.docker.compose.project=//p' | sort -u); do
  case "$proj" in
    "$BASIC_PROJECT"|"$CCAPI_PROJECT"|"$CRM_PROJECT") ;;
    *) other="$other $proj" ;;
  esac
done
if [ -n "$other" ]; then
  die "another branch's validation stack is running:
$(printf '    %s\n' $other)
  It holds ports 5001/7100/4000, which this one needs. Only one branch can be up at a time.
  Stop it first (\`down\` keeps its database volume, so switching back is cheap):
$(printf '    docker compose -p %s down\n' $other)"
fi


# --- 2. checkouts ----------------------------------------------------------------------
step "Checkouts under $VALIDATION_ROOT ($VALIDATION_BRANCH)"
[ "$VERIFY_ONLY" = "--verify" ] || mkdir -p "$VALIDATION_ROOT"

# Not every repo has every branch: credit-card-api has no `mp` at all, and crm's may lag.
# Resolving per repo rather than assuming one branch spans all three is the difference
# between a checkout that fails loudly and one that silently sits on the wrong trunk.
resolve_branch() {   # resolve_branch <repo-with-a-remote> -> echoes the branch to use
  local repo="$1"
  if git -C "$repo" ls-remote --exit-code --heads origin "$VALIDATION_BRANCH" >/dev/null 2>&1; then
    printf '%s' "$VALIDATION_BRANCH"
  else
    printf 'main'
  fi
}

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
    br="$(resolve_branch "$existing")"
    info "$r: adding worktree from $existing at $br"
    git -C "$existing" fetch --quiet origin "$br"
    git -C "$existing" worktree add --quiet "$dest" "origin/$br"
  else
    info "$r: cloning (this takes a while for avant-basic)"
    git clone --quiet "git@github.com:AvantFinCo/$r.git" "$dest"
    br="$(resolve_branch "$dest")"
    git -C "$dest" checkout --quiet "$br"
  fi
  ok "$r ready at $br"
done

# Report the branch each checkout actually sits on, resolved from the checkout itself rather
# than from what we asked for - a pre-existing directory was never touched above, and may be
# on something else entirely. A repo that fell back to main under --branch mp is called out:
# it is often correct (credit-card-api has no mp) and sometimes the whole reason a Run is odd.
: > "$VALIDATION_ROOT/.branch-provenance"
for r in "${REPOS[@]}"; do
  d="$VALIDATION_ROOT/$r"
  sha="$(git -C "$d" rev-parse --short HEAD)"

  # A worktree added from `origin/<branch>` has a DETACHED head, so `--abbrev-ref` says
  # literally "HEAD" and names no branch. What matters is not the branch name anyway but
  # whether this commit is on the trunk under test, so ask that directly - and say how far
  # behind its tip, because a checkout pinned at an old release tag looks identical to one
  # at the tip if you only print a SHA.
  want="origin/$VALIDATION_BRANCH"
  desc="$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  if [ "$desc" = "HEAD" ]; then
    # --exact-match only: a plain `describe` names the NEAREST ref, which is often some other
    # branch's tag and reads as if the checkout were on it.
    tag="$(git -C "$d" describe --all --exact-match HEAD 2>/dev/null | sed 's#^.*/##' || true)"
    [ "$tag" = "HEAD" ] && tag=""   # origin/HEAD names nothing useful
    desc="detached${tag:+/$tag}"
  fi
  if git -C "$d" rev-parse --verify --quiet "$want" >/dev/null; then
    if git -C "$d" merge-base --is-ancestor HEAD "$want" 2>/dev/null; then
      behind="$(git -C "$d" rev-list --count "HEAD..$want" 2>/dev/null || echo '?')"
      if [ "$behind" = "0" ]; then on="on $VALIDATION_BRANCH tip"
      else on="on $VALIDATION_BRANCH, $behind behind tip"; fi
    else
      on="NOT on $VALIDATION_BRANCH"
    fi
  else
    on="no local $want ref - fetch, or this repo has no $VALIDATION_BRANCH"
  fi

  printf '%s\t%s\t%s\t%s\n' "$r" "$desc" "$sha" "$on" >> "$VALIDATION_ROOT/.branch-provenance"
  case "$on" in
    "on $VALIDATION_BRANCH tip") ok "$r @ $sha ($desc) $on" ;;
    *) ok "$r @ $sha ($desc) - $on; stamp this on the Run" ;;
  esac
done
info "origin refs are read as-is, not fetched: 'behind tip' is as of the last fetch"
info "branch provenance written to $VALIDATION_ROOT/.branch-provenance"

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
           config/initializers/zzz_local_mla_stub.rb \
           config/initializers/zzz_local_consolidated_cma.rb \
           config/initializers/zzz_local_render_provenance.rb \
           config/initializers/zzz_local_cma_render.rb; do
    [ -f "$VALIDATION_ROOT/avant-basic/$f" ] || die "missing patch: avant-basic/$f"
  done
  ok "patches present"
else
  AVANT_ROOT="$VALIDATION_ROOT" VALIDATION_BRANCH="$VALIDATION_BRANCH" "$WORKDIR/local-stack/restore.sh" | sed 's/^/  /'
fi

# --- 5. stack --------------------------------------------------------------------------
step "Stack"
if [ "$VERIFY_ONLY" != "--verify" ]; then
  (cd "$VALIDATION_ROOT/avant-basic"     && docker compose -p "$BASIC_PROJECT" up -d web sidekiq >/dev/null)
  (cd "$VALIDATION_ROOT/credit-card-api" && docker compose -p "$CCAPI_PROJECT" up -d web sidekiq >/dev/null)
  (cd "$VALIDATION_ROOT/crm"             && docker compose -p "$CRM_PROJECT"  up -d web >/dev/null)
  info "waiting for basic (first boot restores a large DB dump - can be several minutes)"
fi

for i in $(seq 1 60); do
  code="$(curl -s -o /dev/null -m 25 -w '%{http_code}' http://localhost:5001/ 2>/dev/null || true)"
  [ "$code" = "200" ] && break
  sleep 10
done
[ "${code:-}" = "200" ] || die "basic never returned 200 on :5001 (last: ${code:-none}).
  Check: docker compose -p "$BASIC_PROJECT" logs --tail=50 web"
ok "basic :5001"

curl -s -o /dev/null -m 20 http://localhost:7100/ 2>/dev/null && ok "ccapi :7100" \
  || die "ccapi not answering on :7100"

# The CRM client bundle lives in the container's writable layer, so any recreate loses it
# and every request 500s on `Failed to lookup view "login.ejs"`.
if [ "$VERIFY_ONLY" != "--verify" ]; then
  info "building the CRM client bundle (~53s, required after any recreate)"
  (cd "$VALIDATION_ROOT/crm" && docker compose -p "$CRM_PROJECT" exec -T web sh -c 'cd /app && yarn webpack' >/dev/null 2>&1) || true
fi
crm_body="$(curl -s -m 20 http://localhost:4000/us/ 2>/dev/null || true)"
case "$crm_body" in
  *login.ejs*) die "CRM is serving the login.ejs error - the client bundle is missing.
  Run: cd $VALIDATION_ROOT/crm && docker compose -p "$CRM_PROJECT" exec web sh -c 'cd /app && yarn webpack'" ;;
  *) ok "crm :4000" ;;
esac

# --- 6. the things that fail silently --------------------------------------------------
step "Silent-failure checks"
mocks="$(cd "$VALIDATION_ROOT/avant-basic" && docker compose -p "$BASIC_PROJECT" exec -T web \
  sh -c 'printenv ENABLE_MOCK_SERVICES; printenv MOCK_TRANSUNION' 2>/dev/null | tr -d '\r' | paste -sd, -)"
[ "$mocks" = "1,1" ] || die "mock env vars are '$mocks', expected '1,1'.
  Without them the TransUnion mock never registers and EVERY application declines with
  missing_transunion_report, with no mention of mocks anywhere."
ok "ENABLE_MOCK_SERVICES + MOCK_TRANSUNION"

tf="$(cd "$VALIDATION_ROOT/avant-basic" && docker compose -p "$BASIC_PROJECT" exec -T web \
  sh -c 'printenv AVANT_TEMPLATES_API_KEY | wc -c' 2>/dev/null | tr -d ' \r')"
[ "${tf:-1}" -gt 1 ] || die "AVANT_TEMPLATES_API_KEY did not reach the container.
  Env is baked at container creation. Re-run:
    cd $VALIDATION_ROOT/avant-basic && docker compose -p "$BASIC_PROJECT" up -d --force-recreate web sidekiq
  Never --force-recreate CRM: it wipes the client bundle."
ok "TemplateFlow key reached the container"

# An initializer that exists on disk has told you nothing about whether it RAN. Each of these
# logs a [local] line at boot; assert on the log, not the file. Note the destination: Rails logs
# to log/development.log INSIDE the container, so `docker compose logs` shows none of this.
#
# Read the log ONCE into a variable and match with `case`. `grep ... | grep -qF` looks equivalent
# and is not: the downstream grep exits on its first match, the upstream one dies of SIGPIPE, and
# `set -o pipefail` turns that into a failed check on a log large enough that the write is still
# in flight. It passes on a small log and fails on a big one.
bootlog="$(cd "$VALIDATION_ROOT/avant-basic" && docker compose -p "$BASIC_PROJECT" exec -T web \
  sh -c 'grep -h "\[local\]" log/development.log 2>/dev/null' 2>/dev/null || true)"
for want in 'LocalConsolidatedCma active' 'LocalRenderProvenance active' 'LocalMlaStub active' \
            'FakeTransunion mock registered'; do
  case "$bootlog" in
    *"$want"*) ok "boot log: $want" ;;
    *) die "no '[local] $want' in log/development.log.
  The initializer did not run, so the behaviour it provides is silently absent. Check that
  local-stack/restore.sh put it in config/initializers/ and that the container was recreated." ;;
  esac
done

http="$(curl -s -o /dev/null -m 25 -w '%{http_code}' \
  -H "Api-Key: $AVANT_TEMPLATES_API_KEY" "https://$AVANT_TEMPLATES_HOST/api/v1/templates" || true)"
[ "$http" = "200" ] || die "TemplateFlow returned $http for the templates list.
  401 means the key is wrong. Take STAGING_API_KEY, not API_KEY."
ok "TemplateFlow reachable and the key is accepted"

printf '\nReady. basic :5001   ccapi :7100   CSP :4000/us/\n'
printf 'Checkouts: %s\n' "$VALIDATION_ROOT"
