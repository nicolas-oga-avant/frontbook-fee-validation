# Surface: schumer_box_basic - implemented, needs `--branch mp`

`/schumer_box/<uuid>`, 16 direct codes. Exists only on `mp` (FINDINGS #35 -
`SchumerBoxController`/its route are absent from `main` entirely, confirmed by diffing
`config/routes.rb` across both trunks). This repo works off `main` by default (AGENTS.md hard
rule 7), so this Surface needs a deliberate `mp` bring-up, not a routine one.

To close it for a set of codes:

```bash
.claude/skills/test-frontbook-fee-launch/bootstrap.sh --branch mp   # stop main first - same ports
python3 scripts/run_validation.py <CODE> --check-schumer-static --branch mp --headless
```

`--check-schumer-static` does the real capture+assert on `mp` (not just a probe) - same checker
and same frontbook-before-backbook `--control` rule as `schumer_box_apply`. On any other branch it
stays a live probe only (`blocked` on a 404, `not_applicable` for an MLA code, `not_implemented` if
the route ever resolves somewhere unexpected). Bring `main` back up afterward - only one branch's
stack can be up at a time (same ports).

Verified 2026-09-10 against a fresh `mp` bootstrap: all 16 direct codes pass, 4-of-4 discriminating
absence checks on every backbook capture. Also found while bringing this up: `mp`'s current
`SchumerBoxController`/view no longer match FINDINGS #35's original hardcoded-content description
- it now reads the fee variables dynamically, likely fixed by CSRV-5841 the same day that finding
was written. See FINDINGS #35's own correction note before assuming it is still broken.
