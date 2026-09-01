# PROCEDURE - one Run, end to end

The steps of a single Run. Executed on 2026-08-31 for strategy `0122`; the corrections from that
walk are folded in here, and the raw record is `docs/run-1-walkthrough.md`.

Every step ends with an assertion that the state changed. A step that did not error has told you
nothing (`AGENTS.md`).

## 0. Precondition - Confetti

Cheap, no browser, catches a stale-config false failure before a Run is wasted.

```bash
B=https://confetti.boston.k8s.prd.app.avant.com

curl -s "$B/config?path=basic.pricing_strategy.pricing_strategy_param_to_id&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config'].get('$UUID'))"

curl -s "$B/config?path=basic.pricing_strategy&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config']['$CODE'])"
```

`Avant::Env::Confetti.confetti_env` defaults to `prd` (`avant-basic/lib/avant/env.rb:2788`); only
`.env.development` sets `dev`. If the target app is on `prd` it will not see the dev-only releases
and the new codes appear unconfigured. Confirm before concluding a Run failed.

MLA codes have no UUID and are not reachable this way. That is by design - they are forced (decision
7 in `DESIGN.md`).

## 1. Browser phase

```
http://localhost:5001/apply?product_type=credit_card&strategy=<UUID>
```

An unrecognised UUID redirects to `strategy_param_error_path`
(`avant-basic/app/controllers/apply_controller.rb:72`). Fast, unambiguous, and useful as a control.

| Stage | Actions |
| --- | --- |
| `#/personal` | AUTOFILL PERSONAL STAGE; **set last name to `approved`**; fix phone if it starts with 1; tick consents |
| `#/personal_continued` | AUTOFILL; **overwrite the whole address**; tick consents (an IL-specific one appears) |
| `#/rates_terms` | autofill; **tick `creditHardPullConsent`** |
| `#/password` | set both password fields |
| dashboard `/verify/<app_uuid>` | dev tools -> `Approve Product and Skip Ver` (**needs `element.click()`**, it is off-canvas) |
| `#/congratulations` | approved |

Five browser traps, each failing silently, all handled in `scripts/apply_harness.py`:

1. Clicks below the fold do nothing - the AX box model returns *page* coordinates.
2. `scrollIntoView` does not apply within the same `js()` eval. **Scroll and measure in separate
   calls.** This is the single most important rule in the harness.
3. Consent checkboxes are not HTML-`required`; `checkValidity()` returns true while React refuses.
4. AUTOFILL emits an invalid phone number (area code starting `1`) and an inconsistent address
   (Miami/FL with a Chicago ZIP).
5. Dashboard dev-tools buttons are off-canvas at x=2612 in a 2560 viewport.

To surface a silent block: blur every input, then re-read the page text.

Capture the `application_id` here, explicitly. Never look it up later by recency.

## 2. Console phase

```ruby
OptimizelyInitializer.setup!                 # only under `rails runner`, which has no Optimizely client
cca.issue!                                   # => true; real onboarding, servicing account, CMA log
LocalCmaStub.prepare!(cca.id)                # fills the Fiserv-only fields
log = cca.cardmember_agreement_logs.issuance.find(<id captured from issue!>)
cca.send_email!(:credit_card_product_overview,
  attachment_renderer_inputs: {
    letter_template_name: cca.servicing_account.interface.cardmember_agreement_template_name,
    cardmember_agreement_log_id: log.id,
  })
File.write('/usr/src/app/tmp/cma.html', log.document_html)
File.binwrite('/usr/src/app/tmp/cma.pdf', log.document_pdf)
```

**Do not use `.last` to find the CMA log.** Runs execute concurrently; `.last` returns another Run's
document and the Run goes green having validated the wrong strategy. Capture the id explicitly.

`LocalCmaStub` (`local-stack/zzz_local_cma_stub.rb`) refuses to run on an unissued account and
cross-checks the pricing strategy against the decision path tag. Read its header. `revert!` belongs
in a finally-block, not on the happy path.

**Do not** use the CSP "Download CMA" button or the `.eml`. The CRM route pipes `wkhtmltopdf` inside
an amd64-emulated container and hangs. basic already rendered the identical PDF natively - read
`document_pdf`.

## 3. Assertions

Both layers, on every applicable Run. Full detail in `DESIGN.md`.

- **Layer 1 - value table.** Five assertion points from `data/run-matrix.csv`. Absence is a positive
  assertion for backbook codes: the FX paragraph must not render, the summary row must read `None`.
- **Layer 2 - redline.** Seven assertions from `data/redline-assertions.json`.

Watch the `3%` trap: the only `3%` in a backbook CMA is the cash advance fee ("the greater of $10 or
3%"). Match full sentences.

Record the Template Version and the TemplateFlow instance on the Attempt. Without them a render has
no provenance and cannot be attributed to an Epoch.

## 4. Evidence

Per step: the URL navigated to, values filled, dev helper clicked, console command and its output,
artifacts produced. Evidence is the deliverable, not a side effect - product signs off on the
artifact.

## Baseline

`evidence/baseline/cma_0122_local.{html,pdf}` is the verified pre-change render for `0122`: $28/$39,
no FX fee. That is **correct** for its Epoch. When the new Template Version lands, the identical Run
should flip to $30/$41/3%.

Live state at the end of run 1: local account 5211958 (`0122`, issued, stubbed), application
215412121, CMA log 3778086. `LocalCmaStub.revert!(5211958)` to unpin.
