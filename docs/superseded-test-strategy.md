> **SUPERSEDED - do not act on this file.**
> Kept for provenance only. Several claims here are now known stale (notably: avant-basic#5928
> is merged, no `new_fee_structure` feature flag exists, and the MLA variants ARE reachable).
> The current documents are `DESIGN.md`, `SETUP.md`, `PROCEDURE.md` and `AGENTS.md`.

# Replicable test strategy - frontbook fee launch validation

> ## STATUS: DESIGNED, NOT YET EXECUTED
>
> The config plumbing below (steps 0-1) is **verified working**. Steps 2 onward - the apply flow,
> the identity-bypass helpers, CMA generation, and the CIAM CSP download - were **never walked in a
> browser** during setup, because the session was spent unblocking config. Treat steps 2-6 as a
> plan to validate on the first run, not as a proven runbook. Expect the first run to correct them.
>
> The single biggest unknown is step 5: **whether the CMA is produced at approval time or needs a
> downstream trigger**, and whether the deployed dev CSP can see a customer created via
> `dev.avant.com/apply` at all (see "Known trap: which Basic" below).

## The one-line shape

For each strategy code: apply for a card under that code -> push the application to approval using
the in-UI dev helpers -> retrieve the generated CMA -> assert fee values -> screenshot as evidence.

Parameterise from `run-matrix.csv`. One row = one run. Do the 8 **old** codes first: they assert
already-live content and are unblocked by CSRV-5299.

---

## Step 0 - Confirm the environment is configured (verified)

Cheap, no browser, catches a stale-config false failure before wasting a run.

```bash
B=https://confetti.boston.k8s.prd.app.avant.com

# strategy is URL-reachable? (must print the code you expect)
curl -s "$B/config?path=basic.pricing_strategy.pricing_strategy_param_to_id&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config'].get('$UUID'))"

# fees + APR cap for the code
curl -s "$B/config?path=basic.pricing_strategy&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config']['$CODE'])"
curl -s "$B/config?path=basic.pricing_strategy.apr_caps_by_enabled_timestamp&env=dev" \
  | python3 -c "
import json,sys
print([v for v in json.load(sys.stdin)['config']['values'] if v.get('pricing_strategy_id')=='$CODE'])"
```

**Which Confetti env does the target app read?** `Avant::Env::Confetti.confetti_env` defaults to
`'prd'` (`avant-basic/lib/avant/env.rb:2788`); only `.env.development` sets `dev`, and that is
local-only. CSRV-5297 reports deployed avant-basic dev runs `CONFETTI_ENV=prd` while CCAPI dev runs
`dev`. **If dev basic is on `prd`, it will not see the dev-only releases** and the new codes will
appear unconfigured. This is fixable via Vault + pod restart. Confirm before concluding a run failed.

## Step 1 - Get the UUID for the code (verified)

From `run-matrix.csv`, or live:

```bash
curl -s "$B/config?path=basic.pricing_strategy.pricing_strategy_param_to_id&env=dev" \
  | python3 -c "
import json,sys
print({c:u for u,c in json.load(sys.stdin)['config'].items()}['$CODE'])"
```

MLA codes have **no UUID** and are unreachable this way - by design, not an error. See FINDINGS #3.

## Step 2 - Apply (UNVALIDATED)

```
https://dev.avant.com/apply?product_type=credit_card&strategy={UUID}
```

An unrecognised UUID redirects to `strategy_param_error_path`
(`avant-basic/app/controllers/apply_controller.rb:72`) - a fast, unambiguous failure meaning the
UUID is not in the param map. That redirect is the expected negative case, useful as a control.

## Step 3 - Push the application through with dev helpers (UNVALIDATED)

`avant-basic/app/controllers/account_opening/verification_dev_tools_controller.rb`, routed under
`scope :dev_tools` (`config/routes.rb:1377-1385`):

| Route | Purpose |
| --- | --- |
| `POST .../dev_tools/confirm_ssn` | bypass SSN verification |
| `POST .../dev_tools/confirm_dob` | bypass DOB verification |
| `POST .../dev_tools/confirm_bank_account` | bypass bank verification |
| `POST .../dev_tools/confirm_email` | bypass email confirmation |
| `POST .../dev_tools/email_confirmation_link` | fetch the confirmation link |
| `POST .../dev_tools/complete_current_action` | force-advance the current step |
| `POST .../dev_tools/trigger_mitigation` | trigger a mitigation |

Whether these surface as UI buttons or need to be POSTed directly is unconfirmed.

TransUnion is stubbed in dev (`real_production_TUNA_request?` is false), and the primary pull honours
a **last-name override**: `AppConfig.trans_union.data_stubs.<lastname>_method`
(`lib/avant/trans_union/gateway.rb`). Only `first_pull_stub_method` is configured in
`config/policies/constants/us.yml` today, so no magic last names exist yet - but this is the hook if
you need a specific credit profile. Confetti `basic.mock_scenarios` offers a newer variant-based
mock framework (high/low FICO, credit freeze, name mismatch), but it is an **mp-branch** feature and
`dev.avant.com` serves main-based `basic`.

## Step 4 - Assert the pricing the application was given (UNVALIDATED)

Before the CMA, check the decisioned values, which is where a config gap shows up first:

- **APR** - for these strategies the APR cap *is* the APR. `spread: 1` (`FIXED_APR_SPREAD`) is a
  sentinel making `min(spread + prime_rate, apr_cap)` always return the cap. Expect
  `expected_max_apr` from the matrix. **29.99% where you expected 35.99% means the APR cap entry is
  missing** - see FINDINGS #4, it is the silent failure mode of this whole launch.
- **Annual fee** - `expected_annual_fee_y1` / `_y2`.
- **RPF eligibility** - `CreditCardAccount#rpf_fee_eligible?`, driven entirely by the Optimizely
  flag `card_rpf_fees`. Expect `$25` initial and sequential. See FINDINGS #5 for two traps.

## Step 5 - Retrieve the CMA (UNVALIDATED - biggest unknown)

Intended route: CIAM CSP -> find the customer -> download the CMA from the dashboard.

Open questions to settle on run 1:

1. Is the CMA generated at approval, or does it need a downstream job/trigger? There is a
   `cardmember_agreement_workflow_delay` Optimizely feature, which implies a deliberate delay.
2. Can the deployed CSP see this customer at all? See the trap below.
3. If a console action is required to generate or send it, **stop and ask a human** - Rails console
   in ArgoCD is off-limits to the agent for this work.

### Known trap: which Basic

`dev.avant.com/apply` writes to **`basic`**, but the deployed dev CSP
(`crm.ocala.k8s.dev.global.avant.com`) reads **`basic-mp`**. Disjoint databases: a customer created
by applying will very likely read as *not found* in that CSP. Options if it bites:

- run CRM locally against `basic` (see the root `CLAUDE.md` for the compose-override recipe), or
- use `basic.ocala.k8s.dev.global.avant.com` admin/API directly, or
- apply against a front end wired to `basic-mp` instead.

Resolve this once and record the answer here - it is per-environment, not per-strategy.

## Step 6 - Validate the CMA and capture evidence

Two layers. The value table proves the wiring for every run; the redline comparison is the release
gate. They answer different questions and neither replaces the other.

Do **not** use the `validating-cma-redline` skill. It is pinned to the CSRV-4697 WB redline, expects a
`cma_run_*` before/after artifacts folder we do not produce, and its expensive visual-verification
protocol exists to work around a PDF limitation we avoid by reading the `.docx` directly.

### Layer 1 - value table (all 28 runs)

Assert the expected row from `run-matrix.csv` at five points. Each catches a different failure:

| Point | Assert | Catches |
| --- | --- | --- |
| Confetti | UUID resolves; fees and APR cap present | stale config, before a run is wasted |
| Decisioned application | `expected_max_apr`, annual fee y1/y2 | the missing-cap 29.99% silent failure (#4) |
| CMA inputs (`cma_fee_terms`) | the three integers | the strategy -> numbers boundary, no render needed |
| Rendered CMA | the five template sites | that inputs actually reached the document |
| CSP late fee label | matches the CMA schedule | avant-basic#5928's claim that they cannot disagree |

Absence is a positive assertion, not a gap: for old codes the foreign transaction paragraph must not
render and the summary row must read `None`.

### Layer 2 - redline comparison (every applicable run)

`extract_redline_assertions.py` derives the assertion set from the approved `.docx` and writes
`redline-assertions.json`:

```bash
python3 extract_redline_assertions.py
```

Seven paragraphs, which is the entire approved change surface, each carrying a `new_codes_expect` and
an `old_codes_expect` with fee amounts parameterized as `${late_fee_initial}`,
`${late_fee_subsequent}` and `{foreign_transaction_fee}`. Substitute from the matrix row and compare
against the rendered CMA.

Because the set is seven paragraphs rather than a whole-document legal review, run it on **every**
applicable run rather than a representative sample.

Read FINDINGS #10 and #11 before trusting the output: the approved doc contains a typo that is
normalized here, and two of the old-code expectations come from template gating rather than from the
redline.

Capture a screenshot per run. Keep evidence out of the Jira description - it belongs in the Notion
Results page or a ticket comment.

**AC 2 for new codes cannot pass until CSRV-5299 and CSRV-5298 land.** Until then, run the 8 old base
codes and record the new ones as blocked rather than failed.

## Turning this into a skill

Once run 1 has corrected steps 2-6, the loop is mechanical and worth packaging. The stable parts:
the run matrix as input, step 0 as a precondition gate, and the expected-value table as assertions.
The parts that will need care: dev-helper sequencing (may vary by application state) and CMA
retrieval (unknown until walked).

Do **not** package it before walking it once. Most of the cost in this session came from assuming a
documented path existed.
