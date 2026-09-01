# SETUP - bringing the stack up on any machine

The whole chain only closes locally. Dev/Ocala can drive the apply flow but cannot issue a card:
Fiserv rejects the address, and the overnight onboarding batch is Fiserv's, not ours, so there is no
way to force it. See FINDINGS #3 and the root `CLAUDE.md`.

## Prerequisites

| Need | Note |
| --- | --- |
| Docker with ~8GB available to the VM | three Rails/Node stacks, amd64-emulated on Apple Silicon |
| Checkouts of `avant-basic`, `credit-card-api`, `crm` | siblings in one directory; see `AVANT_ROOT` below |
| Chrome | the harness drives its own instance on a debug port, not yours |
| `kubectl` against `glbdev-use2-eks-ocala` | once, to read the TemplateFlow staging API key |
| Python 3.11+ | the harness and the assertion scripts |

Repo layout is not assumed. `local-stack/restore.sh` defaults to the parent-of-parent-of-parent of
its own location and fails loudly with instructions if the checkouts are not there:

```bash
AVANT_ROOT=/wherever/you/keep/them ./local-stack/restore.sh
```

## Worktrees, not the shared checkouts

Never run against a shared checkout: another session moves its branch under you. Create dedicated
worktrees off `main` (this is production work, not MP work - see `DESIGN.md` decision 4):

```bash
for r in avant-basic credit-card-api crm; do
  git -C "$AVANT_ROOT/$r" fetch origin main
  git -C "$AVANT_ROOT/$r" worktree add "$AVANT_ROOT/$r-frontbook-validation" origin/main
done
```

basic bind-mounts its source (`docker-compose.yml:75`, `.:/usr/src/app`), so a worktree needs no
image rebuild. Volumes are scoped per compose project, so a new worktree starts with an empty
Postgres and restores a large dump on first boot - several minutes. That is expected, once per
Campaign.

## Bring it up

```bash
AVANT_ROOT=... ./local-stack/restore.sh --up
```

That restores the untracked overrides, re-excludes them, starts all three stacks, waits for basic,
and builds the CRM client bundle. Manually, it is:

```bash
docker compose -p basic-csrv-5300 up -d web sidekiq     # localhost:5001
docker compose -p ccapi-csrv-5300 up -d web sidekiq     # localhost:7100
docker compose -p crm-csrv-5300  up -d web              # localhost:4000
docker compose -p crm-csrv-5300  exec web sh -c 'cd /app && yarn webpack'   # REQUIRED, ~53s
```

Project names are ticket-scoped so they cannot collide with another session's stacks.

## Wiring

```
CRM   --API_URL_US-->              http://host.docker.internal:5001
basic --CREDIT_CARD_API_ENDPOINT--> http://host.docker.internal:7100
CCAPI --AVANT_BASIC_HOST_URL-->    http://host.docker.internal:5001
CCAPI --FDR_GATEWAY_URL-->         https://fdr-gateway-asm.ocala.k8s.dev.global.avant.com
basic --AVANT_TEMPLATES_HOST-->    templateflow.ocala.k8s.dev.global.avant.com   (never production - ADR 0001)
```

`AVANT_TEMPLATES_HOST` and `AVANT_TEMPLATES_API_KEY` are read by
`avant-basic/config/initializers/templateflow_engine_client.rb`.

Put both in `.env.local`, which is gitignored and sourced automatically by
`local-stack/restore.sh`:

```bash
cp .env.local.example .env.local && chmod 600 .env.local
kubectl -n templateflow-asm exec deploy/templateflow-01 -- printenv STAGING_API_KEY
# paste into AVANT_TEMPLATES_API_KEY=
```

The key is not in Vault and does not need to be. `avant-templates/app/api/root.rb:17-18` accepts two
bare keys straight from the TemplateFlow pod's own environment - `ENV['API_KEY']` for the prod legacy
user and `ENV['STAGING_API_KEY']` for the staging one - and `lazily_create_legacy_api_user!` creates
the admin user and its `ApiKey` on first use. **Take `STAGING_API_KEY`.** Using `API_KEY` would create
the *prod* legacy admin user inside the staging database.

The credential is never written into `local-stack/*.yml`. The override names
`AVANT_TEMPLATES_API_KEY` with no value, so Compose passes it through from the shell that ran `up`.
Env vars are baked at container creation, so after changing it:

```bash
docker compose -p basic-csrv-5300 up -d --force-recreate web sidekiq   # basic only, never CRM
docker compose -p basic-csrv-5300 exec web sh -c 'printenv AVANT_TEMPLATES_HOST; printenv AVANT_TEMPLATES_API_KEY | wc -c'
```

A character count of 1 means the value never reached the container, and every render will 401.

### Which TemplateFlow

There is no "dev" TemplateFlow. `avant-templates/.avant/terraform/.global-dev.tfvars:1` sets
`environment_override = "stg"`, so the global-dev account's instance **is** the staging deployment;
the `avant-stg-shared-app-*` names are that same stack's legacy AWS resources (Aurora, Redis), not a
second environment. The EKS deployment is `templateflow-01` in namespace `templateflow-asm`
(`locals.tf:3`) on cluster `glbdev-use2-eks-ocala`, reachable at
`templateflow.ocala.k8s.dev.global.avant.com`.

Host verified: `GET /api/v1/templates` returns 401 without a key, which is what
`TemplateflowEngine::Client::Send` maps to "your token is invalid". A 401 *after* setting the key
means the key is wrong, not the host.

("templateflow-01" appears in CSRV-5299's testing plan as though it were a hostname. It is a
deployment name.)

## Environment traps that cost hours

| Trap | Symptom | Fix |
| --- | --- | --- |
| CRM client bundle | every request 500s `Failed to lookup view "login.ejs"` after logging "Listening on port 3000" | `yarn webpack` in the container. Any `--force-recreate` wipes it - it lives in the writable layer, not a volume |
| CCAPI Confetti | onboarding rejected: `pricing_strategy_code does not have a valid value` | CCAPI reads `CONFETTI_URL`, basic reads `CONFETTI_URI`. No default |
| `ENABLE_MOCK_SERVICES` | mocks silently never register | `.env.development` is not loaded by the compose web service; set it explicitly |
| Okta | human gate every session | Against a local basic use password login (`abc123` both sides). Only a remote basic needs Okta |
| `rails runner` | `undefined method 'optimizely_client'` | Not a console. Call `OptimizelyInitializer.setup!` first |
| Cold start | health check concludes basic is down | Local basic answers a cold request in ~7s. Use a generous timeout |

## The local patches

Four untracked files, all backed up in `local-stack/` and replayed by `restore.sh`:

| File | Why it exists |
| --- | --- |
| `avant-basic/docker-compose.override.yml` | points basic at local CCAPI; sets `CONFETTI_ENV`, `ENABLE_MOCK_SERVICES`, `MOCK_TRANSUNION` |
| `avant-basic/config/initializers/zzz_local_transunion_mock.rb` | registers `FakeTransunion`, without which every local application declines (FINDINGS #14) |
| `avant-basic/config/initializers/zzz_local_cma_stub.rb` | `LocalCmaStub` - fills the Fiserv-only fields so a freshly issued card can render a CMA (FINDINGS #15) |
| `avant-basic/config/initializers/zzz_local_mla_stub.rb` | forces MLA-positive TransUnion so the 12 MLA Runs are reachable (FINDINGS #3). **Not yet written** - see `TODO.md` |
| `credit-card-api/compose.override.yml` | live minio image, local basic, dev FDR gateway, and `CONFETTI_URL` |
| `crm/docker-compose.override.yml` | CSP against local basic, password login instead of Okta, host port 4000 |

The `zzz` prefix is load-bearing: these must run after `mock_services.rb`, which enables WebMock.

Apple Silicon: set `platform: linux/amd64` on the CRM service and its build. `Dockerfile.dev`
installs an amd64-only wkhtmltopdf `.deb` that dpkg rejects on arm64.

## Verifying the stack is actually good

Do not assume. Before a Campaign:

1. `curl -s -m 20 localhost:5001` returns 200.
2. CSP loads at `localhost:4000/us/` without a `login.ejs` error.
3. The three `zzz_local_*` initializers are loaded (grep the boot log, do not just check the files
   exist - `ENABLE_MOCK_SERVICES` can silently skip them).
4. Confetti resolves one known UUID from `data/run-matrix.csv`.
5. A CMA renders for the baseline account and the Template Version is readable.
