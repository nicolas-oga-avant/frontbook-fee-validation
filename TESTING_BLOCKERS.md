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
so this PR's merge status never matters for testing.

## 2. Template 9658 v7 approval (CSRV-5895) - RESOLVED; landed

Confirmed landed 2026-09-09: `7M83` and `7M82` both rendered with `render_mode: approved`
(`allow_unapproved: false`) - the approved version already carries all three fee variables. See
`evidence/run-7M83/cma_7M83_log2.provenance.json`. No further re-check needed for this item;
`zzz_local_render_provenance.rb` verifies it fresh on every render regardless, so nothing here can
go stale again in a way that matters.

## 3. schumer_box_apply blocked on CSRV-5843 + CSRV-5844 - RESOLVED, not blocked; walked and passing

CSRV-5843 (CAF `SchumerBox.tsx` fix) is merged, not yet deployed - blocked on an operational lag in
CAF's own prod-deploy pipeline (CSRV-5844), not a policy embargo. `zzz_local_caf_preview_bundle.rb`
tests the fix pre-deploy via CAF PR #168's preview bundle; `bootstrap.sh` asserts that bundle URL
200s at the start of every Run. Walked and all-pass for `0122`; detail in
`surfaces/schumer_box_apply.md`. Not yet done: `9004` and the surface's other four codes.

STATUS: NEEDS RE-CHECK if `bootstrap.sh` reports the preview bundle check failing, and once
CSRV-5844 ships (retire the override then - see `surfaces/schumer_box_apply.md`).

## 4. schumer_box_landing blocked on CSRV-5845 + CSRV-5846 - OPEN, same shape as item 3

CSRV-5845 (avant-redesign disclosure) is merged, not deployed; CSRV-5846 (8 Contentful pages) is
Jira status Blocked, not started. Possibly testable pre-deploy via Contentful preview + avant-redesign
preview deploy. Not yet verified.

## 5. predecisioned_terms - RESOLVED, built; schumer_box_basic - OPEN, same shape as item 4

- `predecisioned_terms`: built and runs today, piggybacked on `cma`'s Layer 1 value-table assertion.
  Detail in `surfaces/predecisioned_terms.md` and FINDINGS #34.
- `schumer_box_basic`: checker implemented and proven, but blocked - FINDINGS #35: `/schumer_box/<uuid>`
  has no route on `main` (only on `origin/mp`), and this repo works off `main` (hard rule 7). Waiting
  on trunk state, not a backlog gap. Record `blocked`, not `not_implemented` (`surfaces/schumer_box_basic.md`).

## 6. CSRV-5823 (Confetti prd promotion: param-to-id + apr-caps) - RESOLVED, not a testing blocker; prd promotion itself is NOT yet safe

Not a testing blocker: `local-stack` pins `CONFETTI_ENV=dev` (SETUP.md:144), so this harness always
reads dev Confetti regardless of prd's promotion state, and dev already carries the 8 new codes
(FINDINGS #2). No Surface here is blocked on CSRV-5823.

Promotion itself is not yet safe: `param_to_id` is what makes a strategy reachable by UUID at all
(FINDINGS #8), independent of `roll_pricing_strategy_configuration` (organic assignment only).
CSRV-5879's launch order puts the CAF release before this promotion specifically because the
promotion is what exposes new codes to real applicants. CSRV-5844 (CAF prod deploy) has not shipped
yet (item 3); CSRV-5845/5846 (landing) have not deployed/started (item 4). Promoting now would make
the new codes directly selectable while `schumer_box_apply` still serves the pre-fix box and
`schumer_box_landing` has no content behind it.

STATUS: NEEDS RE-CHECK once CSRV-5844, CSRV-5845, or CSRV-5846 ship.

## 7. CSRV-5300/5301/5302/5303 all show Jira status "Blocked" - OPEN

Not yet confirmed whether that status is current relative to what is actually testable today (per
items 1-6, more may be unblocked than Jira suggests). Worth asking whoever set that status, or
re-deriving it from `scripts/manifest.py report` - the Manifest is seeded now (item 8).

## 8. data/manifest.json not yet seeded - RESOLVED

Seeded 2026-09-09. CSRV-5302's Pair (`7M82`/`7M83`) is fully recorded - all four Surfaces that
apply to an MLA code, both roles. `scripts/manifest.py report <code>` reflects reality now.
