# TODO - implementation checklist

Tick items as you complete them, in the same edit as the work. **Do not tick an item you have not
verified end to end.** If an item turns out to be wrong, strike it (`~~like this~~`) and say why
rather than deleting it - a wrong item that vanishes gets rediscovered at full cost.

Rules for working through this: `AGENTS.md`. Why it is shaped this way: `DESIGN.md`.

---

## Phase 0 - prove the ground is solid

Nothing below matters if this does not reproduce. Do it first, every time the environment changes.

- [ ] Worktrees created off `origin/main` for `avant-basic`, `credit-card-api`, `crm`
- [ ] `local-stack/restore.sh` runs clean against the worktrees with `AVANT_ROOT` set
- [ ] All three stacks up; CSP loads at `localhost:4000/us/` with no `login.ejs` error
- [ ] The `zzz_local_*` initializers confirmed **loaded from the boot log**, not just present on disk
- [ ] Baseline CMA for `0122` re-extracted and byte-comparable to `evidence/baseline/cma_0122_local.html`
- [ ] Template Version (`git_sha_version`) readable from a render, and recorded

## Phase 1 - console phase

Deterministic, no browser. Wrap this first.

- [ ] Manifest schema defined and seeded from `data/run-matrix.csv` with a content hash
- [ ] Manifest read/write with a lock, write-through on every stage transition
- [ ] Append-only Attempt log; status derived from the newest Attempt
- [ ] `issue!` -> `LocalCmaStub.prepare!` -> render, driven from a script
- [ ] Every handle captured by explicit id. **Audit the codebase for `.last` and remove every one**
- [ ] `LocalCmaStub.revert!` in a finally-block
- [ ] Database identity recorded on each Attempt

## Phase 2 - epoch and provenance

- [ ] Template Version read from the render and stamped on every Attempt
- [ ] TemplateFlow instance host stamped on every Attempt
- [ ] Repo commit SHAs stamped on every Attempt
- [ ] Epoch derived from Template Version alone, never from a fee amount
- [ ] Attempts under a superseded Template Version auto-marked stale and re-queued
- [ ] Prod fidelity check: `GET get_template_details` against prod, compare `git_sha_version`. **Read only**

## Phase 3 - browser phase

- [ ] `scripts/apply_harness.py` ported from browser-harness to a standalone CDP client
- [ ] Own Chrome launched on a debug port; the user's browser never touched
- [ ] One `Target.createBrowserContext` per Run
- [ ] Stage-change assertion after every step; silent blocks surfaced by blur-then-reread
- [ ] Application id captured explicitly at creation
- [ ] Verified zero tokens consumed per Run

## Phase 4 - MLA forcing

- [ ] `zzz_local_mla_stub.rb` written, patching **only** `raw_test_data`'s `transunion_mla` branch
- [ ] Backed up into `local-stack/` and wired into `restore.sh`
- [ ] Asserts `military_lending_act_confirmed` is true AND the resolved strategy is the MLA code
- [ ] Attempts stamped `mla_forced: true`
- [ ] One MLA Run rendered end to end (`3M33`)

## Phase 5 - assertions

- [ ] Layer 1 value table, all five assertion points
- [ ] Absence assertions for backbook codes (no FX paragraph, summary row reads `None`)
- [ ] Layer 2 redline from `data/redline-assertions.json`
- [ ] Full-sentence matching, so the cash-advance `3%` cannot produce a false pass
- [ ] Assertion failures classified as results, never handed to an agent to fix

## Phase 6 - failure handling and resume

- [ ] Mechanical vs Assertion classification at every failure site
- [ ] Hand-off payload complete (see `DESIGN.md` decision 10), including `resume_from`
- [ ] Failure signatures mapped to `FINDINGS.md` entries, quoted by number
- [ ] Resume re-enters at `resume_from` on a bare re-invocation
- [ ] Environment-class failures stop the whole Campaign
- [ ] Interventions recorded on the Attempt and persisted into `local-stack/`

## Phase 7 - concurrency

- [ ] Pipeline: bounded browser stage, wide console/assert stage
- [ ] Measured that concurrency 2 actually beats 1 on this hardware before raising it
- [ ] `--concurrency 1` works as a clean-reproduction fallback
- [ ] A halted Run does not stall the others

## Phase 8 - artifact

- [ ] `artifact-design` skill loaded before writing it
- [ ] Pair-first layout, headline verdict, evidence behind toggles
- [ ] Shows Template Version, instance, SHAs, `mla_forced`, Interventions per Run
- [ ] Baseline-Epoch results visibly distinguished from launched-Epoch results
- [ ] Regenerated after every Run, not only at the end

## Phase 9 - the Campaign

- [ ] `0122` / `0120` Pair green end to end
- [ ] CSRV-5300's four Pairs green
- [ ] All 28 Runs attempted; every non-pass has a recorded reason
- [ ] Artifact published and handed to product

---

## Open items not owned by any ticket

- [ ] File the one-line `raw_test_data` defect in `avant-basic` (FINDINGS #3). It blocks the six
      backbook MLA Runs too, so it is not resolved by any other dependency
- [ ] Verify Ocala `templateflow-01` has avant-templates#74's sha synced (CSRV-5219 is the readiness
      dependency). **If it does not, AC 2 stays blocked regardless of everything else**
- [ ] `roll_pricing_strategy_configuration` still rolls 100% to `0120`, so no application is ever
      *organically* assigned a frontbook code. Does not block URL-driven testing. Flagged on CSRV-5297
- [ ] CSRV-5823 tracks the deferred prd Confetti promotion
