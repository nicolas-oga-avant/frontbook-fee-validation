# Surface: schumer_box_landing - blocked on CSRV-5845 + CSRV-5846

`/credit-card/landing/schumer/<uuid>`, same 16 codes. Blocked: the Contentful landing page does not
carry the fee disclosure until CSRV-5845 (avant-redesign) and CSRV-5846 (the 8 new Contentful pages)
both ship.

**If asked to run this Surface: report it as blocked on those two tickets, record it, and stop.**

```bash
python3 scripts/manifest.py record <CODE> schumer_box_landing blocked --blocked-on CSRV-5845,CSRV-5846
```

Confirmed still blocked 2026-09-03: `0120` 404s on `main` (`evidence/surface-probe-main.json`), and
CSRV-5845's preview deploy was probed against prod for the same code - both are the Gatsby shell with
no disclosure in the body, kept under `evidence/pr-preview/` as the before half so the eventual flip
is evidenced by a before and an after rather than asserted from one post-deploy state. Nothing here
is assertable yet; capture it anyway once CSRV-5846 creates the pages.
