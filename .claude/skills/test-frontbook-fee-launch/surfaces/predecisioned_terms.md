# Surface: predecisioned_terms - implemented

avant-basic, post-decision, before issuance. Applies to all 28 codes - the only application-time
surface an MLA code has, since MLA codes carry no UUID and reach neither Schumer surface nor the
landing page.

`Avant::Decisioning::Interface::Card::Base#predecisioned_terms` carries `late_fee_initial`,
`late_fee_subsequent` and `foreign_transaction_fee` (CSRV-5841), nil for a strategy that
configures none of them. `maximum_late_fee` is a separate key, fixed at the policy constant
`35.0` on every code, frontbook and backbook alike (FINDINGS #34) - not the launch's mechanism,
so it stays pinned rather than asserted against the matrix.

Shares the CMA's applied application and its own script path entirely - `run_validation.py`
records this Surface for free as one of `assert_value_table.py`'s Layer 1 points. There is
nothing to walk here on its own; see `surfaces/cma.md` for the shared assertion mechanics.
