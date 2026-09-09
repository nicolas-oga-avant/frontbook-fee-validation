# Surface: schumer_box_apply - implemented, testable pre-deploy via a local override (see below)

`/apply?product_type=credit_card&strategy=<uuid>`, same 16 codes as `schumer_box_basic`. Unlike the
standalone page, this box exists on `main` today - it is a section of the `personal_continued` apply
stage (`version_config.yml:618`, the same stage that returns `predecisioned_terms`), confirmed
reachable in `evidence/surface-probe-main.json` (a `302`, not a `404`).

**Read FINDINGS #35 first.** The box **is** strategy-driven - it renders the right annual fee for
each code (confirmed: `0122` -> `$0`, `9004` -> the `$125` introductory text) - but both launch rows
are hardcoded regardless of strategy: `Up to $39` and `Foreign Transaction: None` for every code,
frontbook included. So **a frontbook capture is expected to fail both fee assertions today**; that
is the disclosure gap the launch has to close, not a broken capture. The fix site is CAF's
`SchumerBox.tsx` (the React micro-frontend actually serving the page, pinned by `react_index_url` in
`version_config` - not the `avant_views` gem's HAML partials, which carry the same hardcoded rows
but are the legacy Angular renderer and did not render this page).

**Capturing it needs a walk, not a URL** - it exists only part-way through an application:

```python
goto_url(apply_url("0122")); wait_for_load(); wait(8)
autofill_stage(); set_tu_scenario("approved"); fix_autofill_phone(); tick_consents_dom()
submit_stage(); wait(14); wait_for_load()
assert stage() == "personal_continued"
capture_surface("0122", "schumer_account_opening", navigate=False, element="table.schumer-box")
```

Both arguments matter. Without `navigate=False` the capture reloads the apply URL and screenshots
the **first** stage. Without `element` the screenshot clips: the box sits in a 240px scroll window
over a 740px table, and what falls outside is the fee rows. A second Run needs `new_incognito_tab()`
first - the previous applicant's session redirects `/apply` to `/home`.

```bash
python3 scripts/assert_schumer_box.py evidence/run-0122/schumer_account_opening_0122.html \
    --code 0122 --control evidence/run-9004/schumer_account_opening_9004.html
```

Both artifacts, every time: the html is what the checker reads, the png is what product signs off
on, indexed together in `evidence/run-<CODE>/surfaces.json`.

**Run against a real capture 2026-09-03** (`0122` and `9004`, account-opening box). The checker's
assumptions about how the page flattens hold: the box-rendered guard passes and both fee checks fail
on content, not on a pattern. The `CONTROL annual fee row` check is strategy-driven today, so a run
where **only the two launch rows fail** is the pending disclosure, and a run where the control or
the `box rendered` guard fails is a broken capture - a screenshot of the wrong stage fails the fee
rows too.

**If asked to run this Surface: capture and assert it, and report a failing result as the finding it
is (hard rule 2) - never retry the capture to make it pass, and never treat the expected failure as
a reason to skip.**

```bash
python3 scripts/manifest.py record <CODE> schumer_box_apply failed --attempt-json '{
  "stage": "asserted",
  "evidence_dir": "evidence/run-<CODE>/",
  "assertions": [...]
}'
```

**Update 2026-09-09 (TESTING_BLOCKERS.md item 3):** CSRV-5843 is merged (CAF PR #168,
`customer-application-frontend`), not "In Progress" as previously recorded here - only CSRV-5844
(avant-basic's own `react_index_url` bump) remains, and it is blocked on an operational lag in
CAF's prod-deploy workflow, not a policy embargo. `local-stack/zzz_local_caf_preview_bundle.rb`
points this checkout's v6.1 `react_index_url` at CAF PR #168's dev-distribution preview bundle, so
this surface is testable against CSRV-5843's actual fix **before** CSRV-5844 ships - `bootstrap.sh`
asserts that bundle URL returns 200 at the start of every Run and halts otherwise.

The 2026-09-03 capture above predates that override and was walked against the old (`11.4.0`)
bundle, so its FAIL is not evidence of what CSRV-5843 actually fixed.

**Re-walked 2026-09-09 for `0122`.** Confirmed the served apply page's assets and its own dev-tools
"Index URL" both read `micro_frontends/168` (the override is live), then re-ran the exact capture
above. Result: **ALL PASS**.

```
$ python3 scripts/assert_schumer_box.py evidence/run-0122/schumer_account_opening_0122.html --code 0122
Run 0122 (new), summary box all_other

== new  (evidence/run-0122/schumer_account_opening_0122.html)
  PASS box rendered (Annual Fee, Foreign Transaction)
  PASS CONTROL annual fee row quotes $0
  PASS penalty fee ceiling 'Up to $41'
  PASS foreign transaction row '3% of each foreign transaction in U.S. dollars.'
  verdict: ALL PASS
```

CSRV-5843's fix works pre-deploy. Not yet re-walked: `9004` (the introductory-annual-fee control)
and the other four codes this surface owns (`0123`, `3303`, `0120`, `0121`, `3302`) - this result
covers one code, not the full six. Record it in the Manifest once `data/manifest.json` is seeded
(TESTING_BLOCKERS.md item 8):

```bash
python3 scripts/manifest.py record 0122 schumer_box_apply passed --attempt-json '{
  "stage": "asserted",
  "evidence_dir": "evidence/run-0122/",
  "note": "against CAF PR #168 preview bundle override, not the deployed react_index_url"
}'
```
