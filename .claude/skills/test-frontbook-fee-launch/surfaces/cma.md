# Surface: Cardmember agreement (`cma`) - implemented

Requires `SKILL.md` Steps 1-2 done first (stack up, code and expectations loaded). Applies to all
28 codes.

**Fastest path (2026-09-10):** `python3 scripts/run_validation.py <CODE>` runs a Confetti
pre-flight (SKILL.md's "Check Confetti first", so a stale-config code halts in ~1s, no browser)
and Steps 3-6 below in one call - apply (which also captures the account-opening Schumer box for
free), console (issue + render), the Layer 1 value table, the Schumer box assertion, and
`manifest.py record` for `cma`, `predecisioned_terms` and `schumer_box_apply`. `--headless` is off
by default, so its Chrome window is visible the same as a manual walk would be. Drop to the steps
below only when it halts (it prints which stage and re-raises - the traceback is the diagnosis,
not something to route around) or when something needs finer control, e.g. `--skip-manifest` while
re-checking a fix before it counts as an Attempt. See `ROADMAP.md` 2.1 and `surfaces/
schumer_box_apply.md` for what this replaced.

## Step 3 - Apply, in the browser

**Fast path (2026-09-09):** `scripts/apply_driver.py` runs this whole step deterministically - no
per-stage driving, no LLM deciding what to click. `python3 scripts/run_apply_standalone.py <CODE>`
runs it against its own throwaway Chrome with zero browser-harness tool calls (ROADMAP 2.1); piping
the same driver through browser-harness instead is the LLM-driven, token-consuming equivalent -
reach for that only when you specifically want an agent watching and able to react mid-walk (e.g.
diagnosing something new the driver itself does not yet handle). Both reuse every helper and every
workaround below; only the waiting changed (polling for the real signal instead of a fixed
`wait(N)` and a look - see `apply_harness.py`'s "deterministic driving" section for why that
mattered).

```bash
python3 scripts/run_apply_standalone.py 7M83 --password '...'
# or, the LLM-driven equivalent via browser-harness:
CODE=7M83 PASSWORD='...' bash -c 'cat scripts/apply_harness.py scripts/apply_driver.py | browser-harness'
```

Prints `application_uuid` (and everything else Step 4 needs) between `APPLY_RESULT_JSON_START` /
`_END` markers, and writes the same JSON to `evidence/run-<CODE>/apply_result.json`. Raises
`SubmitFailed` with the page's own validation text attached if a stage does not confirm - that is
the moment to drop to the manual walk below and see what actually changed, not to retry the script
blindly.

**Manual walk (fallback, and the reference for what the script above encodes):** Load
`scripts/apply_harness.py` into browser-harness. Every workaround in it exists because of an
observed failure; read its module docstring first.

```
http://localhost:5001/apply?product_type=credit_card&strategy=<UUID>
```

`apply_plan(code)` returns that URL together with the TU last name the code needs, which is the only
safe way to reach an MLA code - the two halves must agree.

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
| `#/personal` | `autofill_stage()`; **then** `set_tu_scenario(plan["tu_last_name"])` - autofill overwrites the last name, and both TU mocks key off it; `fix_autofill_phone()`; `tick_consents_dom()` |
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

**Fast path (2026-09-09):** `scripts/console_runner.rb` is everything below in one script, and
`scripts/run_validation.py` already runs it for you as part of the one-call chain at the top of
this file. Run it on its own only when you already have an `application_uuid` from a manual or
standalone apply and want to continue from here by hand - copy it in and run it once with the
code, the `application_uuid` Step 3 gave you, and (MLA Runs only) the base code:

```bash
docker compose -p "$BASIC_PROJECT" cp scripts/console_runner.rb web:/usr/src/app/tmp/console_runner.rb
docker compose -p "$BASIC_PROJECT" exec -T web bundle exec rails runner /usr/src/app/tmp/console_runner.rb \
    <CODE> <application_uuid> [<mla_base_code>]
```

Prints `credit_card_account_id`, both agreement log ids, the render provenance and the
observations file path between `CONSOLE_RESULT_JSON_START`/`_END`. It raises whatever Ruby raised
on any step - that exception is the evidence; do not rescue it away. Read on for what it runs and
why, or to drive it by hand if something in it needs to be re-diagnosed.

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

# On an MLA Run, the TransUnion MLA report is not pulled by product.approve! - that only happens
# in the New Verifications identity-verification loop (PullAllReports, behind the /verify/<uuid>
# redirect this stack does not run). Pull it explicitly first, or verify! raises "no TransUnion
# MLA report at all" even with the right last name set (FINDINGS #37).
app = CustomerApplication.find_by!(uuid: "<app_uuid>")   # or CustomerApplication.find(<application_id>)
app.run_transunion_mla_report!(force: true)

# Now prove the forcing took. It is silent when it does not: the account simply
# opens under the base code and the Run reports frontbook amounts for a code nobody asked about.
LocalMlaStub.verify!(<application_id>, expected_code: "<CODE>")

cca = CreditCardAccount.find(<cca_id>)
cca.issue!                       # => true. Real onboarding, servicing account, agreement log
LocalCmaStub.prepare!(cca.id)    # Fiserv-only fields, and forces the consolidated CMA

# Sanity, before trusting anything downstream:
raise "wrong strategy" unless cca.current_cardholder_pricing_strategy_identifier.to_s == "<CODE>"
```

`LocalCmaStub` (`local-stack/zzz_local_cma_stub.rb`) refuses to run on an unissued account and
cross-checks the pricing strategy against the decision path tag - read its header. On an MLA Run the
tag holds the **base** code and the account holds the M code; the cross-check maps through
`code_to_mla` rather than comparing them raw. `revert!` belongs
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

**Layer 1 - the value table.** Six points, each catching a different failure:

| Point | Assert | Catches |
| --- | --- | --- |
| Confetti | the UUID resolves; fees and APR cap present | stale config, before the Run is wasted |
| Decisioned application | `expected_max_apr`, annual fee y1/y2 | a missing APR cap, which shows up as 29.99% where you expected 35.99% |
| Agreement inputs | the three `cma_*` integers | the strategy-to-numbers boundary, with no render needed |
| Rendered agreement | the five template sites | that the inputs reached the document |
| CSP labels | match the agreement | that the two cannot disagree |
| RPF | `$25`, from a fresh process | a stale Optimizely datafile (FINDINGS #5) |

Four of the six can only be read from inside the stack. Collect them in the same runner script that
issued and rendered, then assert them outside it:

```ruby
LocalRunObservations.collect!(account: cca.id, application: <application_id>, code: "<CODE>",
                              rendered_html: "evidence/run-<CODE>/cma_<CODE>_log<N>.html")
# => /usr/src/app/tmp/observations_<CODE>.json
```

```bash
docker compose -p "$BASIC_PROJECT" cp web:/usr/src/app/tmp/observations_0122.json \
    evidence/run-0122/observations.json
python3 scripts/assert_value_table.py 0122 --observations evidence/run-0122/observations.json
```

`run_validation.py` already ran this (via `--json`, for `manifest.py record` to consume as data)
and printed the verdict. Run the command above by hand only when you already have the observations
and rendered files and want the human-readable text report instead of re-deriving it from the
Manifest.

Confetti is read live; every other point comes from the observations file. A point with no
observation reports `NOT CAPTURED` and fails the Run - an uncaptured point and a passing one look
identical in a summary, which is the whole reason it is not a skip.

Two expectations in there look wrong and are not. `predecisioned_terms[:maximum_late_fee]` is
asserted to be `35.0`, the policy constant: that surface carries no fee-launch amount at all, and
no FX fee key (FINDINGS #34, and see `surfaces/predecisioned_terms.md`). And a monthly-fee
strategy's year-two figure arrives under `monthly_membership_fee_year_two` rather than the annual
key, so either satisfies the check.

`scripts/redline_text.py` owns the redline and its flattening now, so a sentence cannot drift
between this checker and the Schumer box one - `assert_cma_absence.py` was moved onto it and
re-run on the `0120`/`0122` pair with byte-identical output.

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

Record the result first: `python3 scripts/manifest.py record <CODE> cma <passed|failed> --attempt-json '...'`
(the `attempt-json` shape is in `SKILL.md`, "The Manifest is what makes this additive across
sessions"). `run_validation.py` already does this - for both `cma` and `predecisioned_terms` - as
the last step of its one call, unless `--skip-manifest` was passed; only do it by hand after the
manual walk above. That call is this Surface's contribution to the Manifest. When other Surfaces
ran too, the combined report is `python3 scripts/manifest.py report <CODE>` plus the narrative
below - see `SKILL.md`, "Assembling the report across Surfaces" - not a hand-combined summary.

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

- **An MLA Run's classification is forged**, and the report says so. `LocalMlaStub` supplies a
  positive TransUnion MLA report; everything downstream of it - the `code_to_mla` mapping, the
  render variables, the template - runs unpatched. Stamp `mla_forced: true` on the Attempt.
- **You are validating a draft.** Say so in the report. A draft render proves the pending content is
  correct; it is not evidence that customers receive it today.
- **No product decision** exists on a locally-approved application, so `cma_apr_margin_decimal` is
  nil. Fees are unaffected, but do not trust the APR margin on a variable-rate strategy. Do not
  fabricate a decision to silence it.
- **CSP may show no Late Fee Structure** depending on the CRM branch. Check
  `grep -rn lateFeeStructure src/` before reporting its absence as a defect.
