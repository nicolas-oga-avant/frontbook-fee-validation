# Surface: predecisioned_terms - implemented, discloses late fee and foreign transaction fee

avant-basic, post-decision, before issuance. Applies to all 28 codes - the only application-time
surface an MLA code has, since MLA codes carry no UUID and therefore reach neither Schumer surface
nor the landing page.

`Avant::Decisioning::Interface::Card::Base#predecisioned_terms` carries `late_fee_initial`,
`late_fee_subsequent` and `foreign_transaction_fee` (CSRV-5841), each strategy-derived via
`application.policy.pricing_strategies&.dig(pricing_strategy_id, ...)` and nil for a strategy that
configures none of them. `maximum_late_fee` is a separate key, fixed at the policy constant `35.0`
on every code, frontbook and backbook alike (FINDINGS #34) - not the launch's mechanism, so it
stays pinned rather than asserted against the matrix.

**What it is read and asserted for**: walk `surfaces/cma.md` Step 3 through decisioning (no
issuance, no render needed), then it is one of `assert_value_table.py`'s Layer 1 points -
`expected_max_apr`, both annual fees, the decision path strategy, `late_fee_initial`,
`late_fee_subsequent` and `foreign_transaction_fee` against the matrix row, and `maximum_late_fee`
pinned at `35.0`. See `surfaces/cma.md` Step 5 and FINDINGS #34 for the collection/assertion
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

