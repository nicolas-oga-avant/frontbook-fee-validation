# Surface: schumer_box_apply - implemented, passing via a local override (TESTING_BLOCKERS.md item 3)

`/apply?product_type=credit_card&strategy=<uuid>`, same 16 codes as `schumer_box_basic`. It is not a
page of its own - it is a section of the `personal_continued` apply stage (the same stage that
returns `predecisioned_terms`), reached by walking, not by navigating.

The box is served by CAF's `SchumerBox.tsx` (not the `avant_views` gem's HAML partials - those are
the legacy Angular renderer and did not render this page). Full background on how that was
determined, and the pre-fix defect it replaced, is FINDINGS #35 - read it before assuming either
half of this surface's history.

**This checkout runs against CSRV-5843's fix pre-deploy.** `local-stack/zzz_local_caf_preview_bundle.rb`
points v6.1's `react_index_url` at CAF PR #168's preview bundle instead of the deployed one, since
CSRV-5844 (the real `react_index_url` bump) is stuck on an operational lag, not a policy embargo.
`bootstrap.sh` asserts that bundle URL live at the start of every Run and halts otherwise - see
`TESTING_BLOCKERS.md` item 3 for why. Without that override (or once CSRV-5844 ships for real), the
two launch rows are hardcoded and every frontbook capture fails both fee assertions.

**Fast path (2026-09-10):** `python3 scripts/run_validation.py <CODE>` captures and asserts this
Surface for free as part of its one-call chain - `apply_driver.py`'s `run_apply()` already grabs
this exact capture mid-walk (`capture_surface(code, "schumer_account_opening", ...)`, called right
after `#/personal_continued` loads), so nothing extra is walked. For a backbook code, run its
frontbook sibling through the same script first if you want the absence checks to have teeth (a
`--control`) rather than come back honestly `failed` as "unproven". The manual capture and
`assert_schumer_box.py` invocation below remain the fallback for re-diagnosing a specific capture,
or for driving a code `run_validation.py` doesn't reach.

## Capturing it

Exists only part-way through an application:

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

Both artifacts, every time: the html is what the checker reads, the png is what product signs off
on, indexed together in `evidence/run-<CODE>/surfaces.json`.

## Asserting it

```bash
python3 scripts/assert_schumer_box.py evidence/run-<CODE>/schumer_account_opening_<CODE>.html --code <CODE>
```

`--control <frontbook capture>` is required only for a backbook code - see the script's own
docstring for why. **If asked to run this Surface: capture and assert it, and report whatever the
checker says (hard rule 2) - never retry the capture to force a pass, and never skip it because a
past Run failed.**

**Verified 2026-09-09 for `0122`** against the live override: served page and its dev-tools "Index
URL" both confirmed `micro_frontends/168`, and the assertion is **ALL PASS** - `Up to $41` and `3%
of each foreign transaction in U.S. dollars.` both render. Evidence:
`evidence/run-0122/schumer_account_opening_0122.{html,png}`.

**Verified 2026-09-10 for `0120`** (backbook) through `run_validation.py`, with `0122`'s
already-captured html as `--control`: **ALL PASS** on the box itself, and the control run
(0122's capture, scored under backbook expectations) failed all 4 discriminating checks -
"checks that discriminate: 4 of 4", zero `NO TEETH`. Not yet walked: `9004` and the surface's
other four codes (`0123`, `3303`, `0121`, `3302`).

`run_validation.py` runs the capture, the assertion and the `manifest.py record` call below
automatically as part of its one-call chain - do the following by hand only outside that script:

```bash
python3 scripts/manifest.py record <CODE> schumer_box_apply passed --attempt-json '{
  "stage": "asserted",
  "evidence_dir": "evidence/run-<CODE>/",
  "note": "against CAF PR #168 preview bundle override, not the deployed react_index_url"
}'
```
