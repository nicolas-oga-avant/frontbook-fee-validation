# Surface: schumer_box_apply - implemented, passing via a local override

`/apply?product_type=credit_card&strategy=<uuid>`, 16 direct codes. Not a page of its own - a
section of the `personal_continued` apply stage, reached by walking, not navigating. Served by
CAF's `SchumerBox.tsx` (FINDINGS #35 has the full history of how that was determined).

**This checkout runs against CSRV-5843's fix pre-deploy.**
`local-stack/zzz_local_caf_preview_bundle.rb` points `react_index_url` at CAF PR #168's preview
bundle instead of the deployed one, since CSRV-5844 (the real bump) is stuck on an operational
lag. `bootstrap.sh` asserts that bundle URL live at the start of every Run and halts otherwise.
Without this override (or once CSRV-5844 ships for real), the two launch rows are hardcoded and
every frontbook capture fails both fee assertions - see TESTING_BLOCKERS.md item 3.

`run_validation.py` captures and asserts this Surface for free - `apply_driver.py`'s `run_apply()`
already grabs the capture mid-walk right after `#/personal_continued` loads. For a backbook code,
run its frontbook sibling through the script first for the absence checks to have teeth
(`--control`), or they come back honestly `failed` as "unproven".

## Manual capture (fallback, for re-diagnosing a specific capture)

```python
goto_url(apply_url("0122")); wait_for_load(); wait(8)
autofill_stage(); set_tu_scenario("approved"); fix_autofill_phone(); tick_consents_dom()
submit_stage(); wait(14); wait_for_load()
assert stage() == "personal_continued"
capture_surface("0122", "schumer_account_opening", navigate=False, element="table.schumer-box")
```

Both arguments matter: without `navigate=False` the capture reloads the apply URL and screenshots
the first stage; without `element` the screenshot clips (the box sits in a 240px scroll window
over a 740px table). A second Run needs `new_incognito_tab()` first - the previous applicant's
session redirects `/apply` to `/home`.

```bash
python3 scripts/assert_schumer_box.py evidence/run-<CODE>/schumer_account_opening_<CODE>.html --code <CODE>
```

`--control <frontbook capture>` is required only for a backbook code. Report whatever the checker
says (hard rule 2) - never retry the capture to force a pass.
