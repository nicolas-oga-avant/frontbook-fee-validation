---
name: test-frontbook-fee-launch
description: Runs one end-to-end frontbook fee launch validation locally for a given pricing strategy code - sets up the stack from nothing, drives a card application to approval in the browser, issues the card, renders the cardmember agreement, and asserts the fee content. Use when asked to "validate strategy 0122", "test the frontbook fee launch", "run the fee validation for CSRV-5300/5301/5302/5303", or to check that a backbook code still renders $28/$39 with no foreign transaction fee. This is the LLM-driven version: it drives the browser through browser-harness. Renders go against production TemplateFlow in preview mode, picking up the latest draft of the template.
---

# Frontbook fee launch validation - one Run

Proves that a card issued under a given pricing strategy renders a cardmember agreement with the
right fees. Epic CSRV-4119: late fee $28/$39 -> $30/$41, plus a new 3% foreign transaction fee, on
frontbook codes only.

**You drive this.** Setup is scripted; the browser walk is yours, through browser-harness. A
deterministic replacement for the browser phase is planned - until then expect this to cost tokens.

## Before anything: the one rule

**Assume silence means failure.** Nearly every failure mode here is silent - a form that will not
submit and renders no error, a decline with a misleading reason, a mock that never registered, an
agreement rendered under the wrong strategy. **After every step, assert the state actually changed.**
A step that did not raise has told you nothing.

Two traps that produce a green run validating the wrong product:

- The canned account stub carries pricing strategy `3007`. Always confirm the strategy you asked for.
- `AUTOFILL` produces a Miami/FL address with a Chicago ZIP. Overwrite the whole address.

## Step 1 - Set up

```bash
.claude/skills/test-frontbook-fee-launch/bootstrap.sh
```

Idempotent; `--verify` checks without changing anything. It installs nothing, but it will clone or
add worktrees for `avant-basic`, `credit-card-api` and `crm` under `$VALIDATION_ROOT`
(default `~/Source/avant/frontbook-validation`), restore the local patches, start all three stacks,
and verify the things that fail silently.

It needs one credential: `AVANT_TEMPLATES_API_KEY`, in `.env.local` at the repo root. This is the
**production** TemplateFlow key. If the user does not have one, **ask them** - a teammate can send
their `.env.local`. Do not go looking for it in Vault; it is not there.

Do not proceed on a failed bootstrap. Every one of its checks exists because something downstream
fails silently without it.

## Step 2 - Pick the code and its expectations

Ask the user which pricing strategy code, if they did not say. Then read the row from
`data/run-matrix.csv` - never type expected values from memory.

```bash
python3 - <<'PY'
import csv
CODE = "0122"   # <- the code under test
for r in csv.DictReader(open("data/run-matrix.csv")):
    if r["code"] == CODE:
        print(r)
PY
```

The row gives the strategy UUID, the expected late fees, FX fee, RPF, APR cap, annual fees, the
partner code it replaces, and `reachability`.

`reachability` matters:

- **`direct`** - the code has a UUID and is selectable by URL. 16 of 28.
- **`mla_forced`** - an MLA variant. It has no UUID by design; it is reached by applying under its
  non-MLA twin with a local patch forcing a positive TransUnion MLA report. **That patch is not
  written yet.** If the user asks for an `mla_forced` code, say so and stop rather than running the
  twin and reporting it as the MLA code.

Confirm the expectations back to the user before spending a browser walk on them.

### Check Confetti first

Cheap, no browser, and it catches a stale-config false failure before a Run is wasted:

```bash
B=https://confetti.boston.k8s.prd.app.avant.com

curl -s "$B/config?path=basic.pricing_strategy.pricing_strategy_param_to_id&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config'].get('$UUID'))"

curl -s "$B/config?path=basic.pricing_strategy&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config']['$CODE'])"
```

`Avant::Env::Confetti.confetti_env` defaults to `prd` (`avant-basic/lib/avant/env.rb:2788`); only
`.env.development` sets `dev`. An app on `prd` does not see the dev-only releases, and the new codes
read as unconfigured. Confirm this before concluding a Run failed.

`mla_forced` codes have no UUID and are not reachable this way. That is by design.

## Step 3 - Apply, in the browser

Load `scripts/apply_harness.py` into browser-harness. Every workaround in it exists because of an
observed failure; read its module docstring first.

```
http://localhost:5001/apply?product_type=credit_card&strategy=<UUID>
```

An unrecognised UUID redirects to `strategy_param_error_path`. That is a clean, fast failure meaning
the UUID is not in the param map - not a bug in your walk.

Use a fresh browser context per Run (`new_incognito_tab()`), so one Run's session cannot leak into
another. Keep admin and CSP work in the default profile: an incognito context has no Okta session,
so it cannot reach anything behind SSO.

Let `AUTOFILL PERSONAL STAGE` generate the identity. It produces a fresh randomized one per Run, so
Runs cannot collide on a duplicate customer, and the standard dev TransUnion stub approves it. **Do
not reach for the `TST_00xx` mock catalogue** - it has no approved-card case; every `Card`-labelled
case is a decline or a risk scenario (`docs/mock-test-cases.md`). `TST_0001` is the fallback only if
the default stub ever stops approving.

| Stage | What to do |
| --- | --- |
| `#/personal` | `autofill_stage()`; **then** `set_tu_scenario("approved")` - autofill overwrites the last name, and the TU mock keys off it; `fix_autofill_phone()`; `tick_consents_dom()` |
| `#/personal_continued` | `autofill_stage()`; **`fix_autofill_address()`** - overwrite the whole address; `tick_consents_dom()` (an extra IL-specific consent appears) |
| `#/rates_terms` | `autofill_stage()`; `tick_consents_dom()` - `creditHardPullConsent` is the one that blocks approval |
| `#/password` | `set_input("customer.password", ...)` and `customer.passwordConfirmation` |
| after `CREATE PASSWORD` | redirects to `https://avant.staging-app.avant-test.com/verify/<app_uuid>`, which **this stack does not run**. The walk ends here; capture the app uuid from that URL |
| approval | **server-side, in the console**: `CustomerApplication.find_by!(uuid: ...).product.approve!` |

There is no dashboard step. The customer dashboard is a separate app that the local stack does not
run, so `dev tools -> Approve Product and Skip Ver` cannot be performed - and that endpoint is
broken on `main` regardless (FINDINGS #26, #32).

Six browser traps, all silent, all handled by the harness helpers:

1. **Coordinate clicks do nothing on this flow.** A CDP mouse event on the submit button or a
   consent checkbox reports success and has no effect - no error, no validation copy, only
   `check_session_timeout` on the wire. Use `element.click()`: that is what `submit_stage()`,
   `tick_consents_dom()` and `autofill_stage()` now do (FINDINGS #31).
2. Clicks below the fold do nothing - the accessibility box model returns *page* coordinates.
3. **`scrollIntoView` does not take effect inside the same `js()` eval.** Scroll and measure in
   separate calls. This is the single most important rule in the harness.
4. Consent checkboxes are not HTML-`required`, so `checkValidity()` returns true while React refuses
   to advance.
5. `AUTOFILL` emits an invalid phone number, an internally inconsistent address, and a last name
   that undoes `set_tu_scenario`.
6. The submit button's label differs on every stage, so select it by `type=submit`, never by text.

If a stage will not advance and shows no error: blur every input, then re-read the page text. That
surfaces the block.

Confirm a submit actually happened rather than trusting the absence of an error. On `#/rates_terms`
these three requests all return 200:

```
/api/customer_applications/<id>/save_field
/api/customer_applications/<id>/send_product_details
/api/customer_applications/<id>/submit_page
```

If only `google` / `doubleclick` / `facebook` requests fire, the form never submitted.

**Capture the `application_id` explicitly, now.** Never look it up later by recency - see Step 4.

## Step 4 - Issue and render, in the console

Run against basic:

```bash
cd "$VALIDATION_ROOT/avant-basic"
docker compose -p basic-frontbook-fee-validation exec -T web bundle exec rails runner /usr/src/app/tmp/<script>.rb
```

`rails runner` is not a console: it has no Optimizely client, so **start every script with
`OptimizelyInitializer.setup!`** or you get `undefined method 'optimizely_client'` from somewhere
unrelated-looking.

```ruby
OptimizelyInitializer.setup!

cca = CreditCardAccount.find(<cca_id>)
cca.issue!                       # => true. Real onboarding, servicing account, agreement log
LocalCmaStub.prepare!(cca.id)    # Fiserv-only fields, and forces the consolidated CMA

# Sanity, before trusting anything downstream:
raise "wrong strategy" unless cca.current_cardholder_pricing_strategy_identifier.to_s == "<CODE>"
```

`LocalCmaStub` (`local-stack/zzz_local_cma_stub.rb`) refuses to run on an unissued account and
cross-checks the pricing strategy against the decision path tag - read its header. `revert!` belongs
in a finally-block, not on the happy path, so a crashed Run leaves no pinned account.

`prepare!` also tags the account `needs_consolidated_cma`, and `verify!` raises unless the resolved
template is `:credit_card_cardmember_agreement_consolidated`. That check is not ceremony: the fee
variables exist only on the consolidated agreement, and `credit_card_cardmember_agreement_1` still
hardcodes `$28`/`$39`, so a Run that renders `_1` reports backbook amounts for **any** pricing
strategy and nothing errors (FINDINGS #21). If it raises, check the boot log for
`[local] LocalConsolidatedCma` - the tag does nothing without
`zzz_local_consolidated_cma.rb` loaded.

Note the ordering with `OptimizelyInitializer.setup!` above: with a live Optimizely client the real
`consolidated_cma_enabled?` may well return false, since the flag is not on for a local box. The
per-account override short-circuits ahead of it, so the tag wins either way.

**Never use `.last` to find the agreement log.** An account accumulates several, and picking the
wrong one silently validates a different document. Capture the id from `issue!`.

### Rendering: only one path works

Three entry points exist. Two fail locally for reasons that never mention the agreement:

| Path | What happens |
| --- | --- |
| `product.send_email!(:credit_card_product_overview, ...)` | 422 `Missing Variables: first_name`. It dies rendering the *email subject*, before the attachment |
| `interface.csp_requested_cardmember_agreement_log` | `DataSourceBuildError: annual_membership_fee_amount must be a float`. It regenerates inputs, which need a product decision a locally-approved application does not have |
| `CardmemberAgreementLetter.render_pdf` on a log with **stored** `template_variables` | **works** |

Use `LocalCmaRender` (`local-stack/zzz_local_cma_render.rb`) rather than calling the letter
directly. It performs that render and asserts the three things the output cannot tell you apart:
which template resolved, which *version* of it TemplateFlow served, and whether the render was a
non-persisting preview.

```ruby
src = CardmemberAgreementLog.find(<issuance_log_id>)   # the id captured from issue!
log = CardmemberAgreementLog.create!(
  credit_card_account: cca,
  reason_type: CardmemberAgreementLog::CSP_REQUESTED,
  template_variables: src.template_variables,
)

prov = LocalCmaRender.call!(cca.id, log_id: log.id, expected_code: "<CODE>",
                            out_dir: "/usr/src/app/tmp/run-<CODE>")
puts JSON.pretty_generate(prov)
```

It refuses rather than producing weak evidence when:

- the account is not priced at `expected_code`
- the resolved template is not `credit_card_cardmember_agreement_consolidated`, or that name no
  longer points at `5d5b0b5c-...` (template 9658)
- the log already holds a document - `render_pdf` would return the stored one and send no request,
  so the version id would be a previous render's
- the version the log records disagrees with the one the render actually used
- nothing reached TemplateFlow at all

It writes `<base>.html`, `<base>.pdf` and `<base>.provenance.json` into `out_dir` and returns the
provenance. Copy all three out with `docker cp` into `evidence/run-<CODE>/`.

One render per log. To re-render, create another log from the same `template_variables`.

Do **not** use the CSP "Download CMA" button or the `.eml`. That route pipes `wkhtmltopdf` inside an
emulated container and hangs. basic already rendered the identical PDF natively.

### Where the render goes, and why it is a draft

`AVANT_TEMPLATES_HOST` points at **production** TemplateFlow, and the template under test is the
latest draft. Nothing needs patching: a local stack already renders unapproved drafts in preview
mode, and preview is what keeps this safe.

Two flags do that work, and both default to `!Avant::Env.acts_as_prod?`
(`avant-basic/lib/avant/templateflow/create_document.rb:18-19`):

| Flag | Off means |
| --- | --- |
| `preview` | drafts stop rendering **and** documents start persisting to production |
| `allow_unapproved` | TemplateFlow serves the newest *approved* version, which has no fee variables and hardcodes `$28`/`$39` (FINDINGS #22) - a frontbook Run then reports backbook amounts and nothing errors |

`zzz_local_render_provenance.rb` refuses a cardmember agreement render unless both are on, before
the request is sent, so neither can happen silently - hard rule 3 in `AGENTS.md`, and the argument
is in `docs/adr/0002-render-drafts-against-production-templateflow.md`. It is scoped to the three
CMA templates: loan contracts render with `preview: false` legitimately.

Provenance is the `template_version_uuid`, and the letter path does persist it - on
`cardmember_agreement_logs.template_version_id` (FINDINGS #28, since corrected). `LocalCmaRender`
reads it back and cross-checks it against what the probe saw on the wire. There is no
`git_sha_version` yet. `all_version_uuids` comes back newest-first, so the version in use is its
first entry - useful for saying how far ahead of the approved version the draft is.

## Step 5 - Assert

Two layers. Run both.

**Layer 1 - the value table.** Compare against the matrix row at five points, each catching a
different failure:

| Point | Assert | Catches |
| --- | --- | --- |
| Confetti | the UUID resolves; fees and APR cap present | stale config, before the Run is wasted |
| Decisioned application | `expected_max_apr`, annual fee y1/y2 | a missing APR cap, which shows up as 29.99% where you expected 35.99% |
| Agreement inputs | the three `cma_*` integers | the strategy-to-numbers boundary, with no render needed |
| Rendered agreement | the five template sites | that the inputs reached the document |
| CSP late fee label | matches the agreement | that the two cannot disagree |

**Absence is a positive assertion.** For a backbook code the foreign transaction paragraph must
**not** render and the summary row must read `None`. "I did not find it" is a pass only if the check
would have found it, so run it against a frontbook render as a control in the same pass:

```bash
python3 scripts/assert_cma_absence.py evidence/run-0120/cma_0120_log5.html \
    --control evidence/run-0122/cma_0122_rerender.html
```

Every check must pass on the backbook document **and** fail on the control. One that passes on both
is reported as `NO TEETH` and is worth nothing.

**Layer 2 - the redline.** `data/redline-assertions.json` holds seven assertions derived from the
L&C-approved document, with fee amounts parameterised. Substitute from the matrix row and compare
full sentences.

**The `3%` trap:** the only `3%` in a backbook agreement is the cash advance fee - "the greater of
$10 or 3%". A naive `'3%' in text` check passes for entirely the wrong reason. Match whole
sentences.

**Compare fee content, never bytes.** `evidence/baseline/cma_0122_local.html` was rendered against a
different TemplateFlow instance and legitimately differs in unrelated ways.

## Step 6 - Report

Give the user, for the code under test:

- expected vs actual for every assertion, and a verdict
- the pricing strategy actually resolved, read from
  `cca.current_cardholder_pricing_strategy_identifier` - the CSP never displays it
- the TemplateFlow host, the `template_version_uuid` from the render response, and the fact that it
  was a draft preview - a render with no provenance cannot be attributed to a version
- the evidence: URLs visited, the console transcript, the rendered agreement

Evidence is the deliverable, not a side effect - product signs off on the artifact. Capture, per
step: the URL navigated to, the values filled, the dev helper clicked, the console command and its
output, and the artifacts produced. Save the rendered HTML under `evidence/`.

### The baseline

`evidence/baseline/cma_0122_local.{html,pdf}` is the verified pre-change render for `0122`: $28/$39,
no FX fee. That is **correct** for its Epoch. Once the new template version is live, the identical
Run should flip to $30/$41/3%.

## Known blockers - report these, do not work around them

- **MLA codes are not runnable** until the local TransUnion MLA patch is written.
- **You are validating a draft.** Say so in the report. A draft render proves the pending content is
  correct; it is not evidence that customers receive it today.
- **No product decision** exists on a locally-approved application, so `cma_apr_margin_decimal` is
  nil. Fees are unaffected, but do not trust the APR margin on a variable-rate strategy. Do not
  fabricate a decision to silence it.
- **CSP may show no Late Fee Structure** depending on the CRM branch. Check
  `grep -rn lateFeeStructure src/` before reporting its absence as a defect.

## If something breaks

`FINDINGS.md` in the repo root documents 20 failure modes with symptom, cause, and the file and line
that proves each. Check it before debugging from scratch - most of what goes wrong here has already
gone wrong once and been written up.

If you hit something genuinely new and it costs more than about fifteen minutes, add it to
`FINDINGS.md`. That file is why this runbook is short.
