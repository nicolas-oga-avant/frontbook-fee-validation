> **SUPERSEDED - do not act on this file.**
> Kept for provenance only. Several claims here are now known stale (notably: avant-basic#5928
> is merged, no `new_fee_structure` feature flag exists, and the MLA variants ARE reachable).
> The current documents are `DESIGN.md`, `SETUP.md`, `PROCEDURE.md` and `AGENTS.md`.

# HANDOFF - build the CSRV-5300 e2e validation skill

Written 2026-08-31 at the end of the discovery session. Everything here is **executed**, not
designed. Read this plus `FINDINGS.md` before writing a line of the skill.

**Ticket:** [CSRV-5300](https://avantinc.atlassian.net/browse/CSRV-5300) (and siblings 5301, 5302,
5303, epic [CSRV-4119](https://avantinc.atlassian.net/browse/CSRV-4119)).

---

## 1. What the skill must be

A **self-sufficient script**, not an agent workflow. The agent's job is to launch it, read its
output, and step in only when it stops. Requirements, from the request:

1. Encapsulates the e2e manual test proving the frontbook fee launch works.
2. Runs unattended. No agent orchestration in the happy path.
3. On failure: stops with a **clear, actionable** message aimed at both a human and an agent -
   what broke, which step, what to do next. `FINDINGS.md` is the source for those messages; most
   failure modes here are silent by default and each one already has a diagnosis written up.
4. Logs every action.
5. **Captures evidence per step**: URL navigated to, values filled, dev helper clicked, console
   command run and its output, artifacts produced.
6. Final output is a **Claude Artifact** for product review.

### Non-negotiable design points, learned the hard way

- **Fail loudly on silence.** Almost every failure in this domain is silent: a form that will not
  submit and renders no error, a decline with a misleading reason, a mock that never registered, a
  CMA rendered under the wrong pricing strategy. After every step, assert the state actually
  changed and stop if it did not.
- **Never trust a "looks right" value.** Two near-misses this session would have produced a
  green run validating the wrong product: the canned account stub carries pricing strategy
  `"3007"`, and `AUTOFILL` produces a Miami/FL address with a Chicago ZIP. The script must
  cross-check the strategy against the application's decision path tag on every run.
- **Evidence is the deliverable**, not a side effect. Product signs off on the artifact.

---

## 2. Current state

### Proven working (run 1, strategy `0122`)

Full chain executed on the **local** stack: apply -> approve -> `issue!` -> CMA rendered ->
HTML + PDF extracted -> fee content asserted. Artifacts in this directory:
`cma_0122_local.html` (122,742 bytes), `cma_0122_local.pdf` (78,441 bytes, 10 pages).

The rendered CMA currently shows **$28 / $39 and no FX fee**. That is **correct**: it is a
verified pre-change baseline. Both PRs below are unmerged, so the template still hardcodes the old
amounts. When they land, the identical run should flip to $30 / $41 / 3%.

### Blocked on

| Blocker | State |
| --- | --- |
| [avant-basic#5928](https://github.com/AvantFinCo/avant-basic/pull/5928) (CSRV-5298) | Open. Adds `cma_fee_terms`. 1 unresolved thread (trim comments), no approval yet |
| [avant-templates#74](https://github.com/AvantFinCo/avant-templates/pull/74) (CSRV-5299) | Open, **draft**, checks green |
| [avant-basic#5927](https://github.com/AvantFinCo/avant-basic/pull/5927) | `mp` forward-port; off the critical path |

Until both merge, AC 2 (CMA content) cannot pass for new codes. **Everything else is testable
now**, and the harness should be built and proven against the baseline so that when the PRs land
the only variable is the PRs.

### Unlinked gaps (see FINDINGS #12, and CSRV-5823 which I filed)

- MLA variants (12 of 28 runs) are unreachable in dev - no ticket.
- `roll_pricing_strategy_configuration` still rolls 100% to `0120` - no ticket.
- CSRV-5823 tracks the deferred prd Confetti promotion.

---

## 3. The environment the skill runs against

**Use the local stack.** Dev/Ocala works for the apply flow but cannot issue (Fiserv 455 on a bad
address, and no way to bypass the overnight onboarding). Local is fully controllable.

Three compose projects, all with ticket-scoped names so they cannot collide with other sessions:

```bash
docker compose -p basic-csrv-5300 up -d web sidekiq     # localhost:5001
docker compose -p ccapi-csrv-5300 up -d web sidekiq     # localhost:7100
docker compose -p crm-csrv-5300  up -d web              # localhost:4000
docker compose -p crm-csrv-5300  exec web sh -c 'cd /app && yarn webpack'   # REQUIRED, ~53s
```

Wiring:

```
CRM   --API_URL_US-->             http://host.docker.internal:5001
basic --CREDIT_CARD_API_ENDPOINT--> http://host.docker.internal:7100
CCAPI --AVANT_BASIC_HOST_URL-->   http://host.docker.internal:5001
CCAPI --FDR_GATEWAY_URL-->        https://fdr-gateway-asm.ocala.k8s.dev.global.avant.com
```

Override files are backed up in `local-stack/` - see its README. They are untracked in the repos
and a `git clean -xfd` destroys them.

### Environment traps that cost hours

| Trap | Symptom | Fix |
| --- | --- | --- |
| CRM client bundle | every request 500s `Failed to lookup view "login.ejs"` after logging "Listening on port 3000" | `yarn webpack` in the container. **Any `--force-recreate` wipes it** - it is in the writable layer, not a volume |
| CCAPI Confetti | onboarding rejected: `pricing_strategy_code does not have a valid value` | CCAPI reads **`CONFETTI_URL`**, basic reads **`CONFETTI_URI`**. No default |
| `ENABLE_MOCK_SERVICES` | mocks silently never register | `.env.development` is not loaded by the compose web service; set it explicitly |
| Okta | human gate every session | Against a **local** basic use password login (`abc123` both sides). Only a remote basic needs Okta |
| `rails runner` | `undefined method 'optimizely_client'` | Not a console. Call `OptimizelyInitializer.setup!` first |

---

## 4. The e2e sequence

Detail and code in `RUN-1-WALKTHROUGH.md`; reusable helpers in `apply_harness.py`.

### Browser phase

`http://localhost:5001/apply?product_type=credit_card&strategy=<UUID>` (UUIDs in `run-matrix.csv`).

| Stage | Actions |
| --- | --- |
| `#/personal` | `AUTOFILL PERSONAL STAGE`; **set last name to `approved`**; fix phone if it starts with 1; tick consents |
| `#/personal_continued` | `AUTOFILL PERSONAL_CONTINUED STAGE`; **overwrite the whole address**; tick consents (an IL-specific one appears) |
| `#/rates_terms` | autofill; **tick `creditHardPullConsent`** |
| `#/password` | set both password fields |
| dashboard `/verify/<app_uuid>` | dev tools -> `Approve Product and Skip Ver` (**needs `element.click()`**, it is off-canvas) |
| `#/congratulations` | approved |

Five browser traps, each of which fails silently - all are already handled in `apply_harness.py`:

1. Clicks below the fold do nothing (AX box model returns *page* coords).
2. `scrollIntoView` does not apply within the same `js()` eval - scroll and measure in separate calls.
3. Consent checkboxes are not HTML-`required`; `checkValidity()` returns true while React refuses.
4. `AUTOFILL` emits invalid phone numbers (area code starting `1`) and an inconsistent address.
5. Dashboard dev-tools buttons are off-canvas at x=2612 in a 2560 viewport.

To surface a silent block: blur every input, then re-read the page text.

### Console phase

```ruby
OptimizelyInitializer.setup!                 # only needed under `rails runner`
cca.issue!                                   # => true; real onboarding, servicing account, CMA log
LocalCmaStub.prepare!(cca.id)                # fills the Fiserv-only fields
log = cca.cardmember_agreement_logs.issuance.last
cca.send_email!(:credit_card_product_overview,
  attachment_renderer_inputs: {
    letter_template_name: cca.servicing_account.interface.cardmember_agreement_template_name,
    cardmember_agreement_log_id: log.id,
  })
File.write('/usr/src/app/tmp/cma.html', log.document_html)
File.binwrite('/usr/src/app/tmp/cma.pdf', log.document_pdf)
```

`LocalCmaStub` (`local-stack/zzz_local_cma_stub.rb`) refuses to run on an unissued account and
cross-checks the pricing strategy against the decision path tag. Read its header.

**Do not** use the CSP "Download CMA" button or the `.eml`: the CRM route pipes `wkhtmltopdf`
inside an amd64-emulated container and hangs. basic already rendered the identical PDF natively -
read `document_pdf`.

---

## 5. Assertions

Two layers. Do **not** use the `validating-cma-redline` skill: it is pinned to a different
document and expects a `cma_run_*` folder we do not produce.

**Layer 1 - value table, every run.** Expected values per code are in `run-matrix.csv`. Assert at:
Confetti (precondition), decisioned application, `cma_fee_terms`, the rendered CMA, and the CSP
late-fee label. Absence is a positive assertion: for old codes the FX paragraph must **not** render
and the summary row must read `None`.

**Layer 2 - redline, every applicable run.** `extract_redline_assertions.py` derives 7 assertions
from the approved `.docx` into `redline-assertions.json`, with fee amounts parameterised. Read
FINDINGS #10 and #11 first: the approved doc contains a typo that is normalised, and two old-code
expectations come from template gating rather than from the redline.

**Assertion trap:** the only `3%` in a baseline CMA is the *cash advance* fee
(`the greater of $10 or 3%`). A naive `'3%' in text` check passes for the wrong reason. Match full
sentences, which `redline-assertions.json` already does.

---

## 6. Scope of a full run

28 runs = 14 new codes (AC 1-3) + 14 old codes (AC 4, "backbook untouched"). 16 are runnable;
the 12 MLA variants are not (FINDINGS #3).

CSRV-5300 owns `0122 0123 3303 3M33` and predecessors `0120 0121 3302 3M32`.

Both CMA template variants are already covered by the matrix - `3303`/`9004` render the
introductory-annual-fee box, `0122`/`0123`/`3220`/`5217`/`7213` the all-other box (FINDINGS #10).

---

## 7. Known-imperfect things the skill should report, not hide

- **No product decision** on a locally-approved application, so `cma_apr_margin_decimal` is nil
  (FINDINGS #17). Fees unaffected; do not trust the APR margin on a **variable-rate** strategy,
  which matters for CSRV-5301/5302. Do not fabricate a decision to silence it.
- **`cma_fixed_rate` is nil** for `0122` until #5928 adds it to `PRICING_STRATEGY_CODES_FOR_FIXED_RATE`.
- **CSP shows no Late Fee Structure** on the `feat/CSRV-4368-*` CRM branch - it lacks crm#192.
  Check `grep -rn lateFeeStructure src/` before reporting its absence as a defect.
- **CSP never displays the pricing strategy**, so strategy assignment is inferred there. The
  trustworthy read is `cca.current_cardholder_pricing_strategy_identifier` in console, or the
  `pricing_strategy_code` in the fdr-gateway onboarding payload in Datadog.

---

## 8. Artifact for product

The run's final output. It should carry, per run: strategy code, expected vs actual for every
assertion, pass/fail, and the evidence trail (URLs, screenshots, console transcript, the CMA
itself). Product cares about **fee amounts on the rendered agreement**; engineers care about where
it broke. Serve both - headline verdict first, evidence behind toggles.

Load the `artifact-design` skill before writing it.

---

## 9. File inventory

| File | |
| --- | --- |
| `HANDOFF.md` | this |
| `FINDINGS.md` | 17 findings. **The most valuable file here** - every failure mode with evidence |
| `RUN-1-WALKTHROUGH.md` | the executed run, corrected steps 2-5 |
| `TEST-STRATEGY.md` | the procedure; step 6 rewritten around the two assertion layers |
| `apply_harness.py` | browser-harness helpers; every workaround maps to a real failure |
| `extract_redline_assertions.py` -> `redline-assertions.json` | 7 assertions from the approved redline |
| `redline-LGL-7960-*.docx` | the approved redline. **Read the `.docx`, never a PDF export** |
| `run-matrix.csv` | 28 runs, expected values, UUIDs, dev-runnability |
| `mock-test-cases.md` | the 42 apply-flow mock cases; **no approved-card case exists** |
| `cma_0122_local.html` / `.pdf` | the baseline artifact from run 1 |
| `local-stack/` | backups of the untracked override files |
| `source-sheet-frontbook.csv` | snapshot of the authoritative pricing sheet |

Also referenced, in the **sibling** workdir `../CSRV-5667/`: `build_confetti_payloads.py`,
`uuids.json`, `payloads/` - the Confetti config work that unblocked these tickets.

**A note on timing:** local basic answers a cold request in ~7s. Use a generous timeout in any
health check or the script will conclude it is down when it is merely slow.

Live state at handoff: local account **5211958** (`0122`, `issued`, stubbed), application
215412121, CMA log 3778086. `LocalCmaStub.revert!(5211958)` to unpin.

---

## 10. Suggested build order

1. Bring the stack up and re-extract the baseline CMA for `0122`. If that does not reproduce, fix
   that before writing anything.
2. Wrap the console phase first - it is deterministic and needs no browser.
3. Wrap the browser phase using `apply_harness.py`, asserting a stage change after each step.
4. Add the assertion layers and the evidence log.
5. Publish the artifact.
6. Only then generalise from `0122` to the matrix.

Do not package before a full clean run reproduces end to end. Most of the cost this session came
from assuming a documented path existed.
