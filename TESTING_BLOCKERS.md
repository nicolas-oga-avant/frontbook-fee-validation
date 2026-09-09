# Testing blockers - working scratchpad

Not an owned doc like the others in AGENTS.md's layout table. This is a running list of claimed
testing blockers for the frontbook fee launch, so we can grill each one down to "verified fact" or
"resolved" instead of carrying assumptions forward. Status per item:

- OPEN - not yet checked, or checked and still real
- RESOLVED - checked against a live system or the code itself; written up below with evidence
- NEEDS RE-CHECK - resolved once, but time-sensitive (a live toggle, a deploy) and worth re-verifying
  before it is relied on again

Current state only - once an item is resolved or built, its investigation trail belongs in
FINDINGS.md, an ADR, or the file that owns the topic, not here.

Session context: CSRV-5879 is the launch ticket; CSRV-5300/5301/5302/5303 are the four validation
tickets this repo exists to close.

---

## 1. avant-templates (CSRV-5299) merge status - RESOLVED, not a blocker

The harness always renders the draft directly off production TemplateFlow (hard rule 3 / ADR 0002),
so this PR's merge status never mattered for testing.

## 2. Template 9658 v7 approval (CSRV-5895) - RESOLVED, safe to approve; harness reacts to it live

Approving is a live production toggle affecting every account issued after
`CONSOLIDATED_CMA_CUTOFF_DATE` (2026-04-20), not just new frontbook applicants - but the diff is
wording-neutral (gated entirely on the three fee variables), those variables default to the old
$28/$39/nil values absent Confetti config, and no pricing strategy is organically assigned one of
the 8 codes that carry new fee terms yet (`roll_pricing_strategy_configuration` still rolls 100% to
`0120`). Approving today changes zero current customers; product has been told it is fine to
approve.

**Built.** `zzz_local_render_provenance.rb` checks the approved version's fee variables fresh on
every CMA render and forces whichever `allow_unapproved` value that render actually needs, halting
rather than guessing if the check itself fails (FINDINGS #34).

STATUS: NEEDS RE-CHECK whenever CSRV-5895 actually lands - the 8-code / Confetti-rollout facts this
rests on will drift.

## 3. schumer_box_apply blocked on CSRV-5843 + CSRV-5844 - RESOLVED, not blocked; walked and passing

CSRV-5843 (CAF `SchumerBox.tsx` fix) is merged; CSRV-5844 (avant-basic's `react_index_url` bump) is
blocked on an operational lag in CAF's own prod-deploy workflow, not a policy embargo - CSRV-5879's
launch order puts the CAF release before the Confetti promotion that actually exposes new codes to
real applicants, so deploying CSRV-5843 today is safe and changes nothing for current traffic.

**Built and walked.** `zzz_local_caf_preview_bundle.rb` points `us_avantcredit_credit_card` v6.1's
`react_index_url` at CAF PR #168's dev-distribution preview bundle - the pre-deploy path - without
touching the tracked `version_config.yml` in the shared `avant-basic` checkout (see
`local-stack/README.md` and `SETUP.md` for how). `bootstrap.sh` asserts that bundle URL 200s at the
start of every Run and halts otherwise, since it is an ephemeral CI artifact on another team's
pipeline with no retention guarantee.

Re-walked `0122` against it 2026-09-09: `assert_schumer_box.py ... --code 0122` is **ALL PASS** -
`Up to $41` and the 3% foreign transaction row both render. CSRV-5843's fix is confirmed working
pre-deploy for this code. Detail and the full transcript live in `surfaces/schumer_box_apply.md`.
Not yet done: `9004` and the surface's other four codes.

STATUS: NEEDS RE-CHECK whenever `bootstrap.sh` reports the CAF preview bundle check failing (PR
#168's build can be re-triggered or expire off CloudFront with no other warning), and once
CSRV-5844 ships (see the follow-on note in `surfaces/schumer_box_apply.md` for retiring the override).

## 4. schumer_box_landing blocked on CSRV-5845 + CSRV-5846 - OPEN, same shape as item 3

CSRV-5845 (avant-redesign disclosure) is merged, not deployed; CSRV-5846 (8 Contentful pages) is
Jira status Blocked, not started. CSRV-5879's technical notes say the pre-deploy test is "Contentful
preview plus the avant-redesign preview deploy" - possibly testable via preview paths without either
ticket's production deploy. Not yet verified.

## 5. predecisioned_terms - RESOLVED, built; schumer_box_basic - OPEN, same shape as item 4

- `predecisioned_terms`: built and runs today, piggybacked on `cma`'s Layer 1 value-table assertion
  - nothing separate to walk. `late_fee_initial`, `late_fee_subsequent` and
  `foreign_transaction_fee` are real, strategy-derived keys on `predecisioned_terms` (CSRV-5841,
  Jira status Merged, confirmed on the worktree at commit `d8b53c0`). `assert_value_table.py`'s
  `application_point` asserts those three against the matrix (FINDINGS #34). `maximum_late_fee` is
  a separate, unrelated key that stays pinned to the policy constant `35.0` on every code - not the
  launch's mechanism.
- `schumer_box_basic`: checker (`scripts/assert_schumer_box.py`) is implemented and proven (run
  2026-09-03 against the `schumer_box_apply` capture, same document shape). Blocked because
  FINDINGS #35: `/schumer_box/<uuid>` has no route on `main` at all - it exists only on `origin/mp`,
  and this repo works off `main` (AGENTS.md hard rule 7). Waiting on trunk state, not a backlog gap.
  Record `blocked`, not `not_implemented`, per `surfaces/schumer_box_basic.md`.

## 6. CSRV-5823 (Confetti prd promotion: param-to-id + apr-caps) - OPEN, confirm what it actually gates

`basic.pricing_strategy` (the fee-terms keypath) is already live in both dev and prd. CSRV-5823 is
specifically the other two keypaths (`pricing_strategy_param_to_id`, `apr_caps_by_enabled_timestamp`)
- deferred to prd. Need to confirm which Surfaces actually need those two versus which only need the
fee-terms keypath already in prod. Could mean fewer Surfaces are blocked on CSRV-5823 than assumed.

## 7. CSRV-5300/5301/5302/5303 all show Jira status "Blocked" - OPEN

Not yet confirmed whether that status is current/accurate relative to what is actually testable
today (per items 1-6, more may be unblocked than the Jira status suggests). Worth asking whoever set
that status what specifically it is blocked on, or re-deriving it from the manifest once seeded.

## 8. data/manifest.json not yet seeded - OPEN, tooling gap not a launch blocker

`scripts/manifest.py` and the schema exist, but `data/manifest.json` itself does not exist in this
repo yet. No Run has been recorded into it; all evidence so far lives in `evidence/run-*/`
directories. Needs `scripts/manifest.py seed` before the Manifest reflects reality.
