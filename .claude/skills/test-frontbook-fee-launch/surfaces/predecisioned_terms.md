# Surface: predecisioned_terms - implemented, but discloses neither fee

avant-basic, post-decision, before issuance. Applies to all 28 codes - the only application-time
surface an MLA code has, since MLA codes carry no UUID and therefore reach neither Schumer surface
nor the landing page.

**FINDINGS #34 - this surface carries no fee-launch amount at all.**
`Avant::Decisioning::Interface::Card::Base#predecisioned_terms` has no foreign transaction fee key,
and its one late-fee key, `maximum_late_fee`, is `application.policy.maximum_late_fee` - the constant
`35.0` on every policy version, frontbook and backbook alike. So an assertion written from the
ticket's wording ("read `predecisioned_terms` and assert late fees, FX fee, APR, annual fees") would
fail on every Run against a correct template - not a defect, a gap in what the surface exposes.

**What it is read and asserted for instead**: walk `surfaces/cma.md` Step 3 through decisioning (no
issuance, no render needed), then it is one of `assert_value_table.py`'s Layer 1 points -
`expected_max_apr`, both annual fees, and the decision path strategy, all of which **are**
strategy-derived here. The check pins `maximum_late_fee` at `35.0` explicitly rather than asserting
it against the matrix row, so the gap is recorded on every Run rather than silently passing or
being rediscovered. See `surfaces/cma.md` Step 5 and FINDINGS #34 for the collection/assertion
mechanics (`LocalRunObservations.collect!` -> `assert_value_table.py`) - there is no separate script
for this surface; it shares the CMA's.

**If asked to run this Surface: it runs as part of the value table alongside `cma` for the same
applied application - there is nothing to walk here on its own.**

```bash
python3 scripts/manifest.py record <CODE> predecisioned_terms passed --attempt-json '{
  "stage": "asserted",
  "evidence_dir": "evidence/run-<CODE>/",
  "assertions": [{"layer": "value_table", "point": "predecisioned_terms", "result": "..."}]
}'
```

**Still open, and product's to answer, not a harness gap**: if the applicant is meant to see the new
late fee before they have an account, this surface cannot currently show it. CSRV-5841 (In Progress)
adds `late_fee_initial`, `late_fee_subsequent` and `foreign_transaction_fee` to `predecisioned_terms`
- re-check this finding and the pinned `35.0` when it merges, since the expectation here changes at
that point.
