# Surface: schumer_box_landing - implemented, asserted for real

`/credit-card/landing/schumer/<uuid>`, same 16 codes. Unblocked 2026-09-10: CSRV-5846 imported all
24 landing-page entries (the 8 new strategies plus their predecessors) as Contentful drafts, and
`dev.avant.com` renders unpublished drafts because it builds against Contentful's Preview API
(`redesign-preview.dev.global.avant.com` is equivalent; `uat.avant.com` and `www.avant.com` are not -
both need a real publish, tracked separately). See `avant/.tickets/CSRV-5846/CSRV-5846-NOTES.md` for
the full import/verification trail on the content side.

`scripts/run_validation.py` asserts this Surface for real, independent of the apply/console/cma
flow (it needs no application - addressed purely by the code's strategy uuid, like
`schumer_box_basic`):

1. **Probed live first** (`_probe_reachable`, same helper `schumer_box_basic` uses) - a 404 is
   still `blocked` on CSRV-5845/5846, an MLA code is `not_applicable` (no uuid, FINDINGS #8).
2. **Captured via a standalone Chrome** (`scripts/run_schumer_landing_standalone.py`) - the same
   ROADMAP-2.1-style CDP reuse as the apply walk (`run_apply_standalone.py`): launches its own
   Chrome, execs `apply_harness.py` unmodified into a namespace bound to it, calls
   `capture_surface(code, "schumer_landing")`. Zero browser-harness tool calls, zero LLM
   involvement.
3. **Asserted with `assert_schumer_box.py`**, the same checker `schumer_box_apply` and
   `schumer_box_basic` use, with the same frontbook-before-backbook `--control` rule: a backbook
   code's absence checks only have teeth if its frontbook sibling was already run and its capture
   sits on disk (`evidence/run-<sibling>/schumer_landing_<sibling>.html`).

```bash
LANDING_BASE=https://dev.avant.com python3 scripts/run_schumer_landing_standalone.py 0122
python3 scripts/assert_schumer_box.py evidence/run-0120/schumer_landing_0120.html \
    --code 0120 --control evidence/run-0122/schumer_landing_0122.html
```

Or, for a code already fully run on `cma`/`predecisioned_terms`/`schumer_box_apply` and only
missing this Surface: `python3 scripts/run_validation.py <code> --check-schumer-landing --headless`
- runs and records only this Surface, no application/console/render.

**`LANDING_BASE` matters.** `apply_harness.py`'s default (`APPLY_BASE`, the local stack) is the
wrong host entirely for this surface - it will always 404 there, which reads as "still blocked"
even once Contentful is fully ready. `run_schumer_box_landing()` in `run_validation.py` defaults
`LANDING_BASE` to `https://dev.avant.com` (overridable via `--landing-base` or the env var) and
reassigns `apply_harness.LANDING_BASE` at call time - the module constant is otherwise frozen at
whatever it was when `run_validation.py` first imported `apply_harness`, long before any caller
here gets a say.

**`dev.avant.com`'s WAF blocks `urllib`'s default User-Agent with a 403, not a 404.** Confirmed
2026-09-10: the same URL is 200 for curl (with or without a UA) and for a real Chrome, but 403 for
Python's bare `urllib.request.urlopen`. `_probe_reachable()` sends a browser-like UA now, or every
probe against this host would misreport "check manually" (a 403 is neither the 404 that means
blocked nor the 200 that means proceed) on every single Run.

**The box is client-rendered only.** `SchumerBox.js` opens with
`if (!useIsHydrated()) return null` - the disclosure is absent from the served HTML on every
Schumer page, old or new, so a bare `curl | grep` (or a fetch with no settle time) can never see
it. `capture_surface`'s own `settle` (default 8s after navigation) is enough - proven against all
eight new codes and all eight predecessors in a real browser (CSRV-5846-NOTES.md), and against
`0122`/`0120`, `3303`/`3302`, `3220`/`3219` by this repo's own pipeline.

Verified passing 2026-09-10: `0122`/`0120`, `3303`/`3302`, `3220`/`3219` - all four discriminating
absence checks fire 4-of-4 on every backbook capture (not `NO TEETH`), matching
`schumer_box_apply`'s own precedent for what a real, proven negative assertion looks like.

**Still open, not this Surface's problem:** CSRV-5845/5846 are drafts only as of this check - not
yet published to `www.avant.com`. Re-verify post-publish per CSRV-5846-NOTES.md's own Phase 3 (the
Manifest's per-Attempt history will show both the draft-era pass and the post-publish one, not
overwrite it - AGENTS.md hard rule 1).
