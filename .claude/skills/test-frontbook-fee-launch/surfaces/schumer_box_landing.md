# Surface: schumer_box_landing - implemented, asserted for real

`/credit-card/landing/schumer/<uuid>`, 16 direct codes. Needs no application - addressed purely by
the code's strategy uuid, like `schumer_box_basic`. Unblocked 2026-09-10: CSRV-5846's Contentful
drafts render on `dev.avant.com` (it builds against the Preview API; `uat.avant.com` and
`www.avant.com` do not - both need a real publish).

`run_validation.py` asserts it automatically: probes live first (`blocked` on a 404,
`not_applicable` for an MLA code), then captures via a standalone Chrome
(`scripts/run_schumer_landing_standalone.py`, the same zero-tool-call CDP pattern as the apply
walk) and asserts with `assert_schumer_box.py`, same frontbook-before-backbook `--control` rule as
the other two Schumer surfaces.

For a code already run on `cma`/`predecisioned_terms`/`schumer_box_apply` and only missing this
one: `python3 scripts/run_validation.py <code> --check-schumer-landing --headless`.

Two non-obvious things, if re-diagnosing this by hand:

- **The box is client-rendered only** (`SchumerBox.js` gates on `useIsHydrated()`) - absent from
  the served HTML on every Schumer page, so a bare `curl` can never see it. `capture_surface`'s
  8s settle is enough.
- **`dev.avant.com`'s WAF 403s a plain `urllib` request** (default User-Agent) on a URL curl and a
  real Chrome both reach as 200. `_probe_reachable()` already sends a browser-like UA for this
  reason - if probing this host by hand, do the same or the 403 misreads as "check manually".

Verified 2026-09-10: `0122`/`0120`, `3303`/`3302`, `3220`/`3219` all pass, 4-of-4 discriminating.
Still open, not this Surface's problem: CSRV-5845/5846 are drafts only, not yet published to
`www.avant.com` - re-verify post-publish.
