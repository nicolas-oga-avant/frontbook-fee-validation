# SETUP - bringing the stack up on any machine

The whole chain only closes locally. Dev/Ocala can drive the apply flow but cannot issue a card:
Fiserv rejects the address, and the overnight onboarding batch is Fiserv's, not ours, so there is no
way to force it. See FINDINGS #3.

## The services this touches

The first three run locally, from the checkouts below. The last two are remote - basic reaches
TemplateFlow over HTTP - and the paths are for reading code, not for running anything.

| Service | Path | What it does here |
| --- | --- | --- |
| `avant-basic` | `../avant-basic` | Ruby 2.7 / Rails 5.0. Owns the application, decisioning, pricing strategy resolution, and CMA rendering. The centre of this work |
| `credit-card-api` | `../credit-card-api` | Ruby 2.7 / Rails 5.2. Card accounts, onboarding to Fiserv |
| `crm` | `../crm` | TypeScript / React. The CSP admin portal, used for one assertion point |
| `avant-templates` | `../avant-templates` | The TemplateFlow service. Stores and renders the CMA. **Not a gem** - basic talks to it over HTTP |
| `templateflow-engine` | `../templateflow-engine` | The client gem basic uses to reach TemplateFlow |

## Prerequisites

| Need | Note |
| --- | --- |
| Docker with ~8GB available to the VM | three Rails/Node stacks, amd64-emulated on Apple Silicon |
| Checkouts of `avant-basic`, `credit-card-api`, `crm` | siblings in one directory; see `AVANT_ROOT` below |
| Chrome | the harness drives its own instance on a debug port, not yours |
| A production TemplateFlow API key | ask a teammate; it is not in Vault |
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
basic --AVANT_TEMPLATES_HOST-->    templateflow.avant.com   (production, preview mode - ADR 0002)
```

`AVANT_TEMPLATES_HOST` and `AVANT_TEMPLATES_API_KEY` are read by
`avant-basic/config/initializers/templateflow_engine_client.rb`.

Put both in `.env.local`, which is gitignored and sourced automatically by
`local-stack/restore.sh`:

```bash
cp .env.local.example .env.local && chmod 600 .env.local
```

`AVANT_TEMPLATES_HOST` is **`templateflow.avant.com`** - production. `AVANT_TEMPLATES_API_KEY` is a
production credential; it is not in Vault, so ask a teammate for theirs. Keep it in `.env.local` and
the process environment only, never in `local-stack/*.yml`, which exist to be copied around.

The override names `AVANT_TEMPLATES_API_KEY` with no value, so Compose passes it through from the
shell that ran `up`. Env vars are baked at container creation, so after changing it:

```bash
docker compose -p basic-csrv-5300 up -d --force-recreate web sidekiq   # basic only, never CRM
docker compose -p basic-csrv-5300 exec web sh -c 'printenv AVANT_TEMPLATES_HOST; printenv AVANT_TEMPLATES_API_KEY | wc -c'
```

A character count of 1 means the value never reached the container, and every render will 401.

### Why production, and why this is safe

Renders go out in preview mode, which persists nothing, and pick up the latest **draft** - the
artifact actually under test. Staging is not a usable target: file-backed templates ship after the
fee launch, so there is nothing synced there to validate (FINDINGS #18). The full argument is in
`docs/adr/0002-render-drafts-against-production-templateflow.md`.

**Assert preview is on rather than assuming it.** Anything that makes this stack `acts_as_prod?`
flips it off silently - the render stops picking up the draft and starts writing to production.

## Environment traps that cost hours

| Trap | Symptom | Fix |
| --- | --- | --- |
| CRM client bundle | every request 500s `Failed to lookup view "login.ejs"` after logging "Listening on port 3000" | `yarn webpack` in the container. Any `--force-recreate` wipes it - it lives in the writable layer, not a volume |
| CCAPI Confetti | onboarding rejected: `pricing_strategy_code does not have a valid value` | CCAPI reads `CONFETTI_URL`, basic reads `CONFETTI_URI`. No default |
| `ENABLE_MOCK_SERVICES` | mocks silently never register | `.env.development` is not loaded by the compose web service; set it explicitly |
| Okta | human gate every session | Against a local basic use password login (`abc123` both sides). Only a remote basic needs Okta, and `avantpreview.oktapreview.com` is a different org from production, so there is no session to reuse and an agent cannot complete it |
| `rails runner` | `undefined method 'optimizely_client'` | Not a console. Call `OptimizelyInitializer.setup!` first |
| Cold start | health check concludes basic is down | Local basic answers a cold request in ~7s. Use a generous timeout |
| CRM ports | another project holding 3000 collides | base compose binds `3000:3000` and Compose **appends** ports rather than replacing them, so the container ends up on both 3000 and 4000 |

Chrome's debug port has its own trap that is not diagnosable by curl - see FINDINGS #7 before
concluding the harness cannot connect.

### Platform facts that only matter if you leave local

You should not, but if you do:

- **Ocala hosts two Basic deployments**, `basic` and `basic-mp`, with separate databases and
  disjoint data. A customer created in one is invisible in the other. The deployed dev CSP points at
  `basic-mp`.
- **Dev CCAPI points at `basic-mp`** while ocala `basic` points at dev CCAPI, so the dev triangle is
  crossed. Use `Persistence::Customer.local_find`, never `find`, when inspecting dev data.
- **CCAPI stores no customer PII** by design. Do not expect to verify an address there.
- **Dev-utils accounts are not onboarded to Fiserv.** Their `first_data_account_reference` is a
  fabricated Base64 UUID; real ones look like `C26220125456184007040081`. Any FDR call for such an
  account fails with a 500 that says nothing about the code under test.
- **Deployed dev basic reads prd Confetti** unless `CONFETTI_ENV=dev` is set, so the new codes are
  invisible and the apply URL bounces to `/strategy_param_error` (FINDINGS #12).
- **Non-prod TemplateFlow is `stg`, not `dev`.** The global-dev account's deployment sets
  `environment_override = "stg"`, so anything reasoning about a "dev TemplateFlow" is reasoning
  about something that does not exist.
- **Vault path convention**: `avant/${account_environment}/${service_name}/secrets/<KEY>`, one key
  per sub-path with a single `value` field. Not needed for this work - the one credential involved
  is the production TemplateFlow API key, and it is not in Vault.

## The local patches

Four untracked files, all backed up in `local-stack/` and replayed by `restore.sh`:

| File | Why it exists |
| --- | --- |
| `avant-basic/docker-compose.override.yml` | points basic at local CCAPI; sets `CONFETTI_ENV`, `ENABLE_MOCK_SERVICES`, `MOCK_TRANSUNION` |
| `avant-basic/config/initializers/zzz_local_transunion_mock.rb` | registers `FakeTransunion`, without which every local application declines (FINDINGS #14) |
| `avant-basic/config/initializers/zzz_local_cma_stub.rb` | `LocalCmaStub` - fills the Fiserv-only fields so a freshly issued card can render a CMA (FINDINGS #15) |
| `avant-basic/config/initializers/zzz_local_mla_stub.rb` | forces MLA-positive TransUnion so the 12 MLA Runs are reachable (FINDINGS #3). **Not yet written** - see `ROADMAP.md` |
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
