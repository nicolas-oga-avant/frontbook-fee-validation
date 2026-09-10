# Surface: schumer_box_landing - blocked on CSRV-5845 + CSRV-5846

`/credit-card/landing/schumer/<uuid>`, same 16 codes. Blocked: the Contentful landing page does not
carry the fee disclosure until CSRV-5845 (avant-redesign) and CSRV-5846 (the 8 new Contentful pages)
both ship.

`scripts/run_validation.py` records this Surface automatically every Run, from a live probe of
`/credit-card/landing/schumer/<uuid>` rather than a hardcoded assumption - `blocked` on a 404,
`not_applicable` for an MLA code. If a Run ever reports `not_implemented` instead, that means the
route now resolves (CSRV-5845/5846 shipped) and this surface's real signal is to build the
capture/assert step, not to keep recording `blocked`.

Confirmed still blocked 2026-09-03: `0120` 404s on `main` (`evidence/surface-probe-main.json`), and
CSRV-5845's preview deploy was probed against prod for the same code - both are the Gatsby shell with
no disclosure in the body, kept under `evidence/pr-preview/` as the before half so the eventual flip
is evidenced by a before and an after rather than asserted from one post-deploy state. Nothing here
is assertable yet; capture it anyway once CSRV-5846 creates the pages.
