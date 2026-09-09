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

## 3. schumer_box_apply blocked on CSRV-5843 + CSRV-5844 - RESOLVED, not blocked; local override built

Stub (`surfaces/schumer_box_apply.md`) says blocked on both tickets. Walked down 2026-09-09:

- **CSRV-5843 is merged** (CAF `customer-application-frontend` PR #168, merged 2026-09-04 16:24 UTC,
  auto-cut `v11.5.0`). Not "In Progress" - `ROADMAP.md`'s line to that effect is stale.
- **CSRV-5844 is To Do**, and per its 2026-09-08 comment is blocked on a manual step - the CAF
  Production deploy workflow hasn't run since 2026-07-09 - not on CSRV-5843's merge. It is also
  scoped to the **`mp`** branch's `v/7.0` configs only (Flavio Muller in Slack, 2026-09-08); the
  `main`-side `v/6.1` bump this repo's Surface actually reads is explicitly **out of scope** for
  that ticket. Separate gap, tracked, does not block this item.
- **The "must wait for launch day" premise is wrong.** CSRV-5879's own Launch order puts "CAF release
  published, react_index_url bumped" at step 3, deliberately *before* step 6 ("the two Confetti
  keypaths promoted to prd"), which its technical notes say is last *because* that promotion is what
  actually exposes a new-fee strategy to a real applicant. Deploying CSRV-5843 today is safe and
  intended pre-launch - it changes nothing for current traffic because `pricing_strategy_param_to_id`
  (the key that would route a real applicant onto one of the 8 new codes) isn't in prod yet, and
  `roll_pricing_strategy_configuration` still rolls 100% to `0120` regardless (same shape as item 2,
  one hop upstream). So there is no policy embargo to work around - only an operational lag (no
  owner/date on the CAF prod-deploy run) that is another team's domain and not on this team's
  timeline, so testing still cannot depend on it landing before a Run is needed.

**Pre-deploy path confirmed live 2026-09-09.** CAF's "Dev deploy" workflow runs on every
`pull_request` event (never on merge to `master`) and publishes a preview build to CloudFront's dev
distribution keyed by PR number. PR #168's build is still up:

```
https://d1gm0t5fpu3i9c.cloudfront.net/micro_frontends/168/index.html   -> curled just now, HTTP 200
```

This is the "CAF preview bundle" CSRV-5879's technical notes and FINDINGS #35 / ROADMAP 1.7 already
named as the intended pre-deploy path.

**Built 2026-09-09.** Resolution is `local-stack/zzz_local_caf_preview_bundle.rb`, restored by
`restore.sh` into `avant-basic/config/initializers/`: it prepends onto
`CustomerApplicationEngine::Core::Config`'s singleton class and overrides `load_version_config` so
that, for exactly `us_avantcredit_credit_card` v6.1, the parsed `react_index_url` is replaced with
the CAF PR #168 URL above - **not** by editing the tracked `version_config.yml` on disk. That file
lives in the shared `avant-basic` checkout (hard rule 4): a modified *tracked* file shows up as a
diff in `git status` regardless of `.git/info/exclude`, which only suppresses untracked files -
unlike every other override here, which adds a new file. `Config.for` defaults `flush: true` in
`Rails.env.development?`, so once the initializer is loaded its override re-applies fresh on every
request with no restart needed for further changes. The initializer itself DOES need one, though,
same as any new file under `config/initializers/` - Rails collects that list once at boot. Confirmed
2026-09-09 against a `basic` container that had been running since before this file existed:
`docker compose ... restart web` picked it up (boot log then carried `[local] LocalCafPreviewBundle
active`), and `restore.sh`'s git-visibility check still showed 0 tracked-visible files in
`avant-basic`.

**Walked and confirmed 2026-09-09.** Applied for `0122` against the live override: the served apply
page's script tags and its own dev-tools "Index URL" both read `micro_frontends/168`, and
`assert_schumer_box.py evidence/run-0122/schumer_account_opening_0122.html --code 0122` is
**ALL PASS** - `Up to $41` and `3% of each foreign transaction in U.S. dollars.` both render.
CSRV-5843's fix is confirmed working pre-deploy for this code; see `surfaces/schumer_box_apply.md`
for the full transcript and `evidence/run-0122/schumer_account_opening_0122.{html,png}`. `9004` and
the surface's other four codes are not yet re-walked against the override.

**The retention caveat is real and is now enforced, not just noted.** `bootstrap.sh`'s
"Silent-failure checks" step (Step 6) curls the CAF preview bundle URL and dies with a
halt-and-report (repro steps, and where to look for whether CSRV-5844 shipped in the meantime) if
it is not a 200 - it also checks the `[local] LocalCafPreviewBundle active` boot-log line, same as
every other `zzz_local_*` initializer. This runs at the start of every Run via Step 1 of the SKILL,
so a vanished preview bundle halts before any application is walked, rather than producing a
`schumer_box_apply` capture of the OLD CAF release with nothing saying so.

**Follow-on, not yet done:** if CSRV-5844 ships (CAF's own prod-deploy workflow catches up and
`react_index_url` in the tracked `version_config.yml` is bumped for real), this override becomes
redundant - not wrong, since it always points at the *same* fixed content regardless of what the
tracked file says, but worth retiring so a future session isn't left wondering why the preview
bundle check still gates every Run. Re-check Jira/the file diff periodically (see item 2's pattern)
and remove `zzz_local_caf_preview_bundle.rb` from `restore.sh` and the boot-log/curl checks in
`bootstrap.sh` once it lands.

STATUS: NEEDS RE-CHECK whenever `bootstrap.sh` reports the CAF preview bundle check failing (PR
#168's build can be re-triggered or expire off CloudFront with no other warning) and once CSRV-5844
actually ships.

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
