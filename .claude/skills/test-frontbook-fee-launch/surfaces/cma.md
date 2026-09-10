# Surface: Cardmember agreement (`cma`) - implemented

`python3 scripts/run_validation.py <CODE>` runs the whole thing - apply, console (issue + render),
the value table, the Schumer box captured mid-apply, and every `manifest.py record` call. This
file is what to check when it halts, not a parallel way to run it by hand.

## Apply stage traps (if driving the browser by hand to re-diagnose a halt)

Six silent browser traps `scripts/apply_harness.py`'s helpers already handle - relevant only if
bypassing them to debug something new:

1. **Coordinate clicks do nothing on this flow** - a CDP mouse event on the submit button or a
   consent checkbox reports success and has no effect, no error, no validation copy. Use
   `element.click()` (FINDINGS #31).
2. Clicks below the fold do nothing - the accessibility box model returns *page* coordinates.
3. **`scrollIntoView` does not take effect inside the same `js()` eval** - scroll and measure in
   separate calls.
4. Consent checkboxes are not HTML-`required`, so `checkValidity()` returns true while React
   refuses to advance.
5. `AUTOFILL` emits an invalid phone number, an internally inconsistent address, and a last name
   that undoes `set_tu_scenario`.
6. The submit button's label differs on every stage - select by `type=submit`, never by text.

If a stage will not advance and shows no error: blur every input, then re-read the page text.
Confirm a submit actually happened rather than trusting the absence of an error - on
`#/rates_terms`, `save_field`/`send_product_details`/`submit_page` should all return 200; if only
`google`/`doubleclick`/`facebook` requests fire, the form never submitted.

**Capture the `application_id` explicitly, the moment it exists.** Never look it up later by
recency (AGENTS.md hard rule 1).

## Console stage: only one rendering path works

Three entry points exist. Two fail locally for reasons that never mention the agreement:

| Path | What happens |
| --- | --- |
| `product.send_email!(:credit_card_product_overview, ...)` | 422 `Missing Variables: first_name` - dies rendering the *email subject*, before the attachment |
| `interface.csp_requested_cardmember_agreement_log` | `DataSourceBuildError: annual_membership_fee_amount must be a float` - regenerates inputs, which need a product decision a locally-approved application does not have |
| `CardmemberAgreementLetter.render_pdf` on a log with **stored** `template_variables` | works - this is what `console_runner.rb`/`LocalCmaRender` use |

`local-stack/zzz_local_cma_render.rb`'s `LocalCmaRender` is the only path that also asserts what
the output cannot tell you apart: which template resolved, which *version* TemplateFlow served,
and whether the render was a non-persisting preview. It refuses rather than producing weak
evidence when the account is mispriced, the template isn't the consolidated one, the log already
holds a document, or the recorded version disagrees with the wire.

**`rails runner` is not a console: it has no Optimizely client.** Start any one-off script with
`OptimizelyInitializer.setup!` or you get `undefined method 'optimizely_client'` from somewhere
unrelated-looking deep in `generate_cardmember_agreement_inputs` (confirmed 2026-09-10
investigating FINDINGS #40 - the crash itself, not the CMA logic, is the artifact of the one-off
process).

**Why the render is safe and is a draft:** `AVANT_TEMPLATES_HOST` is production TemplateFlow, and
`preview`/`allow_unapproved` both default to `!Avant::Env.acts_as_prod?` - a local stack renders
the latest unapproved draft and persists nothing. `zzz_local_render_provenance.rb` refuses a CMA
render unless both flags are on, before the request is sent (AGENTS.md hard rule 3,
`docs/adr/0002`). Without `allow_unapproved` TemplateFlow serves the newest *approved* version,
which can lack the fee variables entirely - a frontbook Run then reports backbook amounts and
nothing errors (FINDINGS #22).

## Known blockers - report these, do not work around them

- **An MLA Run's classification is forged**, and the report says so. `LocalMlaStub` supplies a
  positive TransUnion MLA report; everything downstream runs unpatched. Stamp `mla_forced: true`.
- **You are validating a draft.** A draft render proves the pending content is correct; it is not
  evidence that customers receive it today.
- **No product decision** exists on a locally-approved application, so `cma_apr_margin_decimal`
  is nil. Fees are unaffected; do not trust the APR margin on a variable-rate strategy, and do not
  fabricate a decision to silence it.

## Assertions

Two layers, both run by `run_validation.py` automatically. Layer 1 (`assert_value_table.py`) is
six points including RPF - four of the six can only be read from inside the stack
(`LocalRunObservations.collect!`). Layer 2 (`data/redline-assertions.json`) is whole-sentence
matches against the L&C-approved redline, never a bare substring - the only `3%` in a backbook
agreement is the cash advance fee, so `'3%' in text` passes for entirely the wrong reason.

**Absence is a positive assertion.** For a backbook code the launch paragraphs must NOT render,
and "I did not find it" is a pass only if the check would have found it - `assert_cma_absence.py`
always runs against a frontbook control in the same pass. A check passing on both is reported
`NO TEETH` and is worth nothing.
