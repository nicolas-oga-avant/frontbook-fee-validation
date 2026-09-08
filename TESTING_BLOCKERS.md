# Testing blockers - working scratchpad

Not an owned doc like the others in AGENTS.md's layout table. This is a running list of claimed
testing blockers for the frontbook fee launch, so we can grill each one down to "verified fact" or
"resolved" instead of carrying assumptions forward. Status per item:

- OPEN - not yet checked, or checked and still real
- RESOLVED - checked against a live system or the code itself; written up below with evidence
- NEEDS RE-CHECK - resolved once, but time-sensitive (a live toggle, a deploy) and worth re-verifying
  before it is relied on again

Session context: CSRV-5879 is the launch ticket; CSRV-5300/5301/5302/5303 are the four validation
tickets this repo exists to close.

---

## 1. avant-templates (CSRV-5299) merge status - RESOLVED, not a blocker

Originally flagged as "In Progress, not merged" as if that gated CMA testing. Wrong: the harness
always renders the draft directly off production TemplateFlow (hard rule 3 / ADR 0002), so the PR's
merge status never mattered for testing. Confirmed live 2026-09-08 that the draft still carries the
fee content regardless.

## 2. Template 9658 v7 approval (CSRV-5895) - RESOLVED, safe to approve; harness needs to react to it

Was flagged as unclear whether approval must wait for launch day. Walked all the way down:

- Approving the draft is a **live production toggle**, not launch-scoped: every account issued after
  `CONSOLIDATED_CMA_CUTOFF_DATE` (2026-04-20, confirmed in prod) already resolves to template 9658,
  approved or not. So approval changes content for ~5 months of already-issued accounts, not just new
  frontbook applicants.
- Checked the actual diff (user): no wording changes, every change is conditioned on
  `late_fee_initial` / `late_fee_subsequent` / `foreign_transaction_fee`.
- `cma_fee_terms` (CSRV-5298, `avant-basic`) defaults absent Confetti config to `28`/`39`/`nil` -
  byte-for-byte the old hardcoded values. Verified in code.
- Confetti prod (`basic.pricing_strategy`, live-checked 2026-09-08): only 8 codes carry fee-term
  entries (`0122 0123 3220 3303 5217 7105 7213 9004`), all `30/41/3`. Everything else has no entry.
- `roll_pricing_strategy_configuration` still rolls 100% to `0120`, so no account is organically
  assigned any of those 8 codes yet.
- CSRV-5298 confirmed **deployed to prod** (not just merged to `main`): GitHub deployments API shows
  SHA `d8b53c037...` deployed to `prd` 2026-09-08T19:32:14Z, and `b9474dc73` (the CSRV-5298 merge
  commit) is an ancestor of it.

Conclusion: approving today changes zero current customers. Product has been told it is fine to
approve.

**Follow-on work (agreed, not yet built):** the harness must stop assuming un-approved and instead
detect approval automatically. Design agreed 2026-09-08:

- Before every CMA render, call `GetTemplateDetails` fresh (bypass `Caches::Templates`, no
  `allow_unapproved`) and check whether **all three** fee variables are present on the approved
  version.
- All three present -> render `preview: true, allow_unapproved: false` (explicit `false` - the local
  default is `true`, so omitting it would silently keep testing draft mode forever).
- Any missing -> render `preview: true, allow_unapproved: true` (today's behavior).
- Check itself fails (unreachable, malformed) -> **halt the Run**, no default guess either way.
- Stamp the decision (`render_mode`, approved `version_uuid`) onto the Attempt's provenance.
- Lives in `zzz_local_render_provenance.rb`, replacing the current unconditional "both flags true"
  refusal.

STATUS: NEEDS RE-CHECK once implemented and again whenever CSRV-5895 actually lands - the 8-code /
deployed-SHA facts above are dated 2026-09-08 and will drift.

## 3. schumer_box_apply blocked on CSRV-5843 + CSRV-5844 - OPEN, same shape as item 1, worth re-checking

Stub (`surfaces/schumer_box_apply.md`) says blocked on both tickets. CSRV-5843 (CAF Schumer box code)
is **merged, not deployed**; CSRV-5844 (`react_index_url` bump) is **To Do, not started**. But
CSRV-5879's own technical notes say the pre-deploy test is "point `react_index_url` at the CAF preview
bundle" - i.e. there may be a preview-bundle path that does not need CSRV-5844 to ship at all, the
same way the CMA draft never needed CSRV-5299/5895 to ship. Not yet verified either way.

Next step: find out whether a CAF preview bundle actually exists and is reachable today, the same way
the TemplateFlow draft was reachable via `allow_unapproved`.

## 4. schumer_box_landing blocked on CSRV-5845 + CSRV-5846 - OPEN, same shape as item 3

CSRV-5845 (avant-redesign disclosure) is **merged, not deployed**; CSRV-5846 (8 Contentful pages) is
Jira status **Blocked**, not started. CSRV-5879's technical notes say the pre-deploy test is
"Contentful preview plus the avant-redesign preview deploy" - again, possibly testable via preview
paths without either ticket's production deploy. Not yet verified.

## 5. predecisioned_terms / schumer_box_basic "not yet implemented" - OPEN, but not blocked on anyone else

No external ticket blocks these two - they are just unbuilt in this repo's harness
(`surfaces/predecisioned_terms.md`, `surfaces/schumer_box_basic.md`). Backlog item, not a real
blocker. Listed here so it does not get mistaken for one during grilling.

## 6. CSRV-5823 (Confetti prd promotion: param-to-id + apr-caps) - OPEN, confirm what it actually gates

`basic.pricing_strategy` (the fee-terms keypath) is already v17 in **both** dev and prd (confirmed
live in item 2). CSRV-5823 is specifically the **other** two keypaths (`pricing_strategy_param_to_id`,
`apr_caps_by_enabled_timestamp`) - deferred to prd. Need to confirm exactly which Surfaces actually
need those two keypaths (Schumer box UUID lookups, most likely) versus which only need the fee-terms
keypath already in prod. Could mean fewer Surfaces are blocked on CSRV-5823 than assumed.

## 7. CSRV-5300/5301/5302/5303 all show Jira status "Blocked" - OPEN

Not yet confirmed whether that status is current/accurate or stale relative to what is actually
testable today (per items 1-6, more may be unblocked than the Jira status suggests). Worth asking
whoever set that status what specifically it is blocked on, or just re-deriving it from the manifest
once seeded.

## 8. data/manifest.json not yet seeded - OPEN, tooling gap not a launch blocker

`scripts/manifest.py` and the schema exist and were verified against a scratch copy, but
`data/manifest.json` itself does not exist in this repo yet. No Run has been recorded into it; all
evidence so far lives in `evidence/run-*/` directories. Needs `scripts/manifest.py seed` before the
Manifest reflects reality.
