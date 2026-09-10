# Surface: schumer_box_basic - checker implemented, unreachable on `main`

`/schumer_box/<uuid>` on dev-mp, for the 8 base codes and their 8 predecessors - no application
needed, just the code's UUID from the matrix row. Assertions derive from the same
`data/redline-assertions.json` `summary_box` entries the CMA's absence checks already use
(FINDINGS #10), flattened by the same `scripts/redline_text.py` both checkers share.

**FINDINGS #35 - the route does not exist on `main`.** `config/routes.rb` on `origin/main` has no
`schumer` route and no `SchumerBoxController`; both exist only on `origin/mp`. Confirmed empirically
2026-09-03 against the running `main` stack: `/schumer_box/<uuid>` 404s for every code, recorded in
`evidence/surface-probe-main.json`. This repo works off `main` (AGENTS.md hard rule 7), so this
Surface cannot be walked here today - that is a trunk gap, not a per-code block, and not the same
thing as the disclosure being absent from the page.

`scripts/assert_schumer_box.py` is the checker and already exists and is proven - just not against
this surface's own capture. It was run 2026-09-03 against the sibling `schumer_box_apply` capture
(same document shape, same redline assertions) and both fee checks failed on content as expected,
with the box-rendered guard and the absence-check `NO TEETH` rule (4 of 4 discriminate) both
holding. See `surfaces/schumer_box_apply.md`.

`scripts/run_validation.py` records this Surface automatically every Run, from a live probe of
`/schumer_box/<uuid>` (not from this file's `main`-only assumption, which would go stale the
moment a Run points at `mp`) - `blocked` on a 404, `not_applicable` for an MLA code. If a Run
against `mp` ever reports `not_implemented` instead, that is this surface's real signal to wire
the capture below into `run_validation.py` - the route resolved, and nothing has ever asserted it.

Once run against dev-mp, the capture and assertion are the same shape as `schumer_box_apply.md`'s:

```python
url, _ = surface_urls("0122")["schumer_basic"]
capture_surface("0122", "schumer_basic")   # html + png into evidence/run-0122/, indexed in surfaces.json
```

```bash
python3 scripts/assert_schumer_box.py evidence/run-0120/schumer_basic_0120.html \
    --code 0120 --control evidence/run-0122/schumer_basic_0122.html
```

Expect the `Up to $41` ceiling row and the `3% of each foreign transaction in U.S. dollars.` row on
frontbook (Row A governs; Row B is an approved-doc typo), `Up to $39` and a Foreign Transaction row
reading `None` on backbook. An MLA code has no UUID and no strategy-addressable box at all -
`surface_urls()` and `assert_schumer_box.py` both refuse it rather than passing while asserting
nothing; record it `not_applicable`, never `not_implemented`, on an MLA code.
