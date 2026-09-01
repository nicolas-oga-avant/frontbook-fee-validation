# DESIGN - the frontbook fee validation skill

What is being built, and why each choice is the way it is. Vocabulary in `CONTEXT.md`. Rules of
engagement in `AGENTS.md`.

## Purpose

A self-sufficient script that runs the end-to-end manual test proving the frontbook fee launch
(epic CSRV-4119) works, so product can sign off before release.

- Runs unattended in the happy path. No agent orchestration, no token cost per Run.
- Logs every action and captures evidence per step.
- Stops with a clear, actionable message when it cannot proceed.
- Final output is a Claude Artifact for product review.

## The unit model

A **Run** is one execution against one Pricing Strategy Code: apply, approve, issue, render, assert.
A **Pair** is a frontbook Run plus the backbook Run it replaces - the unit of evidence, because
"backbook untouched" is only expressible across both. A **Ticket** (CSRV-5300..5303) is a reporting
bucket with no scope of its own.

28 Runs: 14 frontbook (AC 1-3) + 14 backbook (AC 4).

| Ticket | Frontbook | Backbook |
| --- | --- | --- |
| CSRV-5300 | 0122, 0123, 3303, 3M33 | 0120, 0121, 3302, 3M32 |
| CSRV-5301 | 3220, 3M90, 5217, 5M87 | 3219, 3M89, 5216, 5M86 |
| CSRV-5302 | 7213, 7M83, 7105, 7M95 | 7212, 7M82, 7104, 7M94 |
| CSRV-5303 | 9004, 9M04 | 9003, 9M03 |

## Decisions

### 1. One Manifest for all 28 Runs

Seeded from `data/run-matrix.csv`, which carries a `ticket` column, both directions of
`replaces_or_replaced_by`, and a `reachability` column (`direct` or `mla_forced`). The schema is
`data/manifest.schema.json` - a committed contract, so two agents cannot invent two shapes. The four tickets are one procedure parameterised by code, so splitting
into four manifests would mean four seeds off one source and four artifacts to reconcile.

**The caller passes one code, never two.** The partner is derived from the matrix. Typing both
reintroduces the mispairing error the generated matrix exists to eliminate, and a mispaired Pair
produces a green Campaign comparing the wrong things.

### 2. Manifest entries are append-only Attempt logs

Each Run holds an ordered list of Attempts; status derives from the newest. An earlier Attempt is
never overwritten.

Required, not cosmetic: an Attempt superseded by a later Template Version must stay readable, or the
evidence that made it stale is destroyed along with it. It also turns "flaky" into a countable fact.

Cost: never read the newest Attempt without checking its Template Version, or the false-green comes
straight back.

### 3. Bare invocation means "advance the Manifest"

No parameters in the normal case. Selection order:

1. Refuse to start if `data/run-matrix.csv` no longer hashes to the Manifest's `seeded_from`.
2. Take a lock. The checkouts and the stack are shared.
3. Resume any halted Run first - it holds an issued account cheaper to finish than to redo.
4. Otherwise take the next pending Run, preferring to complete a half-done Pair.
5. Write the Manifest after every stage transition, not at the end. Regenerate the artifact.

Flags are escape hatches only: `--run <code>`, `--reset <code>`, `--reseed`, `--only frontbook|backbook`,
`--reuse-account <cca_id>`, `--concurrency N`.

Deliberately absent: `--skip-assert` (skipping an assertion is how a green run proves nothing) and
any manual epoch switch (see 5).

### 4. Fresh worktrees off `main`, in every repo

This is production work, not MP work. The root `CLAUDE.md` rule about basing on `mp` governs where
code is written; this skill writes none. avant-basic#5928 targets `main`, #5927 is the `mp`
forward-port and off the critical path, and the other three repos have no `mp` branch at all.

Never rely on the shared checkouts: they sit on whatever branch another session left them on.
Record the resolved commit SHA per repo on every Attempt.

### 5. Epoch is a Template Version, not a flag

**There is no feature flag.** The `new_fee_structure` flag named in CSRV-5299's description does not
exist; avant-basic#5928 carries a spec asserting it is not emitted. avant-basic supplies three bare
integers resolved per strategy from Confetti:

| Variable | Frontbook | Unconfigured strategy |
| --- | --- | --- |
| `cma_late_fee_initial` | 30 | 28 (Ruby default) |
| `cma_late_fee_subsequent` | 41 | 39 (Ruby default) |
| `cma_foreign_transaction_fee` | 3 | absent, never 0 |

The template supplies the `$` and the `%`. Late fees interpolate unconditionally; only the foreign
transaction disclosures are gated, on the variable being present.

Since CSRV-4904 the CMA templates are git-backed (`app/templates/cma/agreement_base.liquid`, one
file, five variants as internal Liquid conditionals), each carrying a `git_sha_version`. So the
Epoch is exactly that sha, read from the render.

**Except on Ocala today, where it is null.** CSRV-4904 landed in the repo but the staging sync
(CSRV-5219) has not run, so Ocala's CMA records carry neither `git_sha_version` nor `source_file` -
see FINDINGS #18. Until that sync lands, the Epoch signal is a SHA256 of the template `content`
returned by `GET /api/v1/templates/<uuid>`, which needs no git-backing. Record both fields; prefer
`git_sha_version` whenever it is present. It is detected, never configured: a human-set epoch
flag is wrong precisely in the week the change lands.

**Epoch detection must never read a fee amount.** "Does the CMA say $30" is the assertion itself;
using it to choose the expectation makes every Run tautologically pass.

When the Epoch advances, passing Attempts recorded under the old Template Version are marked stale
and re-queued automatically.

### 6. Render on Ocala, verify prod by reading

See `docs/adr/0001`. Rendering is `POST /documents` - a write. Fidelity to production comes from
`GET get_template_details` against prod and comparing `git_sha_version`, plus the existing
`cma:reconcile` rake task for engine-level drift.

Instance selection is two env vars read by
`avant-basic/config/initializers/templateflow_engine_client.rb`: `AVANT_TEMPLATES_HOST` and
`AVANT_TEMPLATES_API_KEY`.

### 7. All 28 Runs are RENDERED - MLA is forced locally

The 12 MLA Runs were thought unreachable. They are not: the block is one hardcoded line in
`avant-basic/lib/avant/trans_union/gateway.rb`, where `raw_test_data`'s `transunion_mla` branch
returns `:mla_negative_stub` unconditionally while the `transunion` branch directly above it honours
a last-name override. The positive fixture exists and is verified valid (the `07051`/`01`/`M01`
addon triple). See FINDINGS #3.

A local `zzz_local_mla_stub.rb` patches that one branch. Constraints:

1. **One method, one line.** Any patch touching `mla_customer?`, pricing-strategy resolution, or the
   render path invalidates the evidence.
2. **Assert the forcing worked** - `military_lending_act_confirmed` true AND the resolved strategy is
   the MLA code. The stub can load and still resolve negative.
3. **Stamp the Attempt** `mla_forced: true` so the artifact shows it.

This is acceptable because it forges the *input* (applicant classification), which is upstream of
everything under test. The chain being validated - Confetti resolves `3M33` to the `3303` entry via
`pricing_strategy_code_to_mla`, then render variables, then template - runs unpatched.

### 8. One long-lived database, isolation by identity

Volumes are per compose project and a fresh worktree means a multi-minute dump restore. Resetting
between Runs is incompatible with concurrency: you cannot reset a shared Postgres under concurrent
workers.

So: restore once per Campaign. Contamination is prevented by the never-`.last` rule, not by
isolation. Requires:

1. Every Run tags its application with a marker encoding the Run id, so an orphan stays attributable.
2. `LocalCmaStub.revert!` runs in a finally-block. A crashed Run must not leave a pinned account.
3. The Manifest records the database identity, so an Attempt from a destroyed database is marked
   unreproducible rather than silently trusted.

### 9. Parallelism: isolated browser contexts, no agent in the loop

`Target.createBrowserContext` gives a genuinely separate cookie jar per Run - not shared-incognito.
The script drives its own Chrome on a debug port via raw CDP, so a Run costs zero tokens.
`scripts/apply_harness.py` currently calls browser-harness helpers and must be ported to a
standalone CDP client; the logic ports directly, being already raw CDP and JS strings.

Pipeline rather than a flat pool: the browser stage is the contended one, the console and assertion
stages fan out wide. Start at 2 browser / 6 console and raise once measured - the containers run
amd64-emulated on Apple Silicon, so worker count scales worse than core count suggests.

### 10. Mechanical vs Assertion failures

**Mechanical**: the apparatus broke - a click that missed, a stage that did not advance, the stack
down, a patch that did not load. The Run halts, hands off to an agent with a resumable payload, and
the rest of the Campaign continues.

**Assertion**: a rendered or resolved value disagrees with the expected one. Recorded as `failed`.
**No agent is invited to fix it.** Handed an assertion failure with "fix it so it can continue", the
cheapest path to green is weakening the assertion, which an agent will do plausibly and with a good
explanation. That yields a signed-off artifact for a fee launch that shipped wrong.

Hand-off payload, written to the Manifest and to stderr:

| Field | |
| --- | --- |
| Run + Attempt id, Pricing Strategy Code | which Run |
| Step | applied / approved / issued / cma_rendered / asserted |
| Expected vs observed | which state change did not happen |
| Diagnosis | the matching `FINDINGS.md` entry, quoted, by number |
| Suggested action | the concrete next command |
| Evidence dir | screenshots, DOM dump, console transcript, HTTP log |
| Handles | cca_id, application_id, cma_log_id |
| `resume_from` | the step to re-enter at |

Diagnosis is the load-bearing field. A failure reading "form did not submit" makes an agent
re-derive what FINDINGS #14 already explains.

**The whole Campaign stops** for environment-class failures - wrong Template Version resolved,
Confetti missing a code, database identity changed. Those invalidate every subsequent Run.

### 11. Resume is a fresh invocation, not a paused process

The agent's fix is usually a code edit; a paused process holds the old code in memory. So the script
exits, the agent fixes, and re-invokes bare - the Manifest routes it back to `resume_from`. This also
makes the loop survive crashes and context resets.

Step-level resume works because state is durable server-side: after `applied` the application
exists, after `issued` the account exists. Even a browser-stage resume is fine, since the apply flow
is server-staged - a fresh context navigating to the application's current stage lands where it left
off. No browser state needs to survive.

Interventions are recorded on the Attempt and persisted into `local-stack/`.

### 12. The artifact

One artifact per Campaign, regenerated after every Run. Pair-first, because the Pair is the
product-facing claim:

```
0120 -> 0122   FX fee introduced, late fee $28/$39 -> $30/$41
  backbook  0120   $28 / $39 / none   PASS (5/5 value, 7/7 redline)
  frontbook 0122   $30 / $41 / 3%     PASS (5/5 value, 7/7 redline)
```

Per Run behind toggles: expected vs actual per assertion, Template Version, TemplateFlow instance,
repo SHAs, `mla_forced`, Interventions, and the evidence trail. Product cares about fee amounts on
the rendered agreement; engineers care about where it broke. Headline verdict first, evidence behind
toggles. Load the `artifact-design` skill before writing it.

## Assertions

Two layers, both on every applicable Run.

**Layer 1 - value table.** Expected values per code in `data/run-matrix.csv`, asserted at five
points, each catching a different failure:

| Point | Assert | Catches |
| --- | --- | --- |
| Confetti | UUID resolves; fees and APR cap present | stale config, before a Run is wasted |
| Decisioned application | expected_max_apr, annual fee y1/y2 | the missing-cap 29.99% silent failure (FINDINGS #4) |
| CMA inputs | the three integers | the strategy-to-numbers boundary, no render needed |
| Rendered CMA | the five template sites | that inputs reached the document |
| CSP late fee label | matches the CMA schedule | that the two cannot disagree |

Absence is a positive assertion: for backbook codes the FX paragraph must NOT render and the summary
row must read `None`.

**Layer 2 - redline.** `scripts/extract_redline_assertions.py` derives seven assertions from the
approved `.docx` into `data/redline-assertions.json`, fee amounts parameterised. Read FINDINGS #10
and #11 first: the approved document contains a typo that is normalised, and two backbook
expectations come from template gating rather than from the redline.

Do not use the `validating-cma-redline` skill - it is pinned to a different document and expects a
`cma_run_*` folder this does not produce. CSRV-5299 ships `CSRV-5299-REDLINE.md`, a cleaner
extraction of the same source; prefer it over re-deriving.

**Assertion trap:** the only `3%` in a backbook CMA is the cash advance fee ("the greater of $10 or
3%"). A naive `'3%' in text` check passes for the wrong reason. Match full sentences, which
`data/redline-assertions.json` already does.

## Known-imperfect things to report, never hide

- **No product decision** on a locally-approved application, so `cma_apr_margin_decimal` is nil
  (FINDINGS #17). Fees unaffected, but do not trust the APR margin on a variable-rate strategy,
  which matters for CSRV-5301/5302. Do not fabricate a decision to silence it.
- **CSP shows no Late Fee Structure** on the `feat/CSRV-4368-*` CRM branch, which lacks crm#192.
  Check `grep -rn lateFeeStructure src/` before reporting its absence as a defect.
- **CSP never displays the pricing strategy.** The trustworthy read is
  `cca.current_cardholder_pricing_strategy_identifier` in console, or the `pricing_strategy_code` in
  the fdr-gateway onboarding payload in Datadog.
