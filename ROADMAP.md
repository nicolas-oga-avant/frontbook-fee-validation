# ROADMAP - the objective, the two phases, and what is left

The single planning document for this project, and the only place dated status lives. `DESIGN.md` is
how, `AGENTS.md` is the rules, `FINDINGS.md` is what goes wrong.

Tick items as you complete them, in the same edit as the work. **Do not tick an item you have not
verified end to end.** If an item turns out to be wrong, strike it (`~~like this~~`) and say why
rather than deleting it - a wrong item that vanishes gets rediscovered at full cost.

---

## The goal

Prove that the frontbook fee launch (epic CSRV-4119) renders correctly on the cardmember agreement,
for every affected pricing strategy, so product can sign off **before** release. 28 Runs: 14
frontbook codes carrying the new fees, and the 14 backbook codes they replace, which must render
unchanged.

The deliverable is evidence, not a green console. Product signs off on an artifact showing the fee
amounts on a real rendered agreement.

### What every Run renders against

**Production TemplateFlow**, picking up the **latest draft** of the **consolidated** cardmember
agreement - template 9658, `5d5b0b5c-9e69-4bb4-aaa5-68581f7e7c93`, currently v7 draft. Preview mode
keeps it safe: see `docs/adr/0002-render-drafts-against-production-templateflow.md`.

It is specifically the consolidated template, not `credit_card_cardmember_agreement_1`, and the
difference is load-bearing - `_1` has none of the fee variables, so a Run that renders it reports
backbook amounts no matter which pricing strategy it was built for (FINDINGS #21). Reaching the
consolidated template locally **does** need a patch: `show_consolidated_cma?` is false by default
because the Optimizely flag is stubbed and `CONSOLIDATED_CMA_CUTOFF_DATE` is unset.

Provenance is the Template ID **and** the `template_version_uuid` the render returns - the version
alone does not say which template it is a version of. No `git_sha_version` exists anywhere yet
(FINDINGS #18).

## Dependency state as of 2026-09-02

| Dependency | State |
| --- | --- |
| avant-basic#5928 (CSRV-5298, `cma_fee_terms`) | **Merged** 2026-08-28 into `main` |
| avant-templates#74 (CSRV-5299, CMA content) | **Open, draft**, base `main` |
| Production CMA draft (template 9658, consolidated) | **v7 draft carries the new fee content** (FINDINGS #21) |
| CSRV-4904 (template extraction to git-backed Liquid) | Merged |
| Confetti `basic.pricing_strategy` (fees) | v17, dev and prd |
| Confetti param-to-id / apr-caps (+8 UUIDs) | dev only; prd promotion deferred to CSRV-5823 |
| Optimizely RPF audience + staging fee amounts | done, both environments |

**There is no `new_fee_structure` feature flag.** It was in CSRV-5299's description and never
existed. Fee content is gated on the *presence* of Confetti-supplied variables (FINDINGS #9).

The baseline render in `evidence/baseline/` shows $28/$39 and no FX fee. That is **correct** - it is
a verified pre-change render, and it should flip to $30/$41/3% once the new template version is live.

---

## Phase 1 - end-to-end, LLM in the loop  (IN PROGRESS)

A skill that takes a machine from nothing to a validated Run. It costs tokens per Run and that is
accepted: the point is that the whole chain closes and a teammate can run it today.

Shipped as `.claude/skills/test-frontbook-fee-launch/`.

### 1.1 Environment, from nothing

- [x] `bootstrap.sh` clones or worktrees `avant-basic`, `credit-card-api`, `crm` off `main`
- [x] Restores the local patches via `local-stack/restore.sh`, which takes `AVANT_ROOT`
- [x] Starts all three stacks and waits for basic properly (cold start is ~7s+, first boot minutes)
- [x] Builds the CRM client bundle, and fails loudly on the `login.ejs` symptom if it is missing
- [x] Refuses to run when a `basic-frontbook-fee-validation` stack is already up from another directory, before
      doing any checkout work
- [x] Verifies the silent failures: mock env vars, the key reaching the container, TemplateFlow
      accepting it
- [x] **Ran `bootstrap.sh` end to end 2026-09-02, exit 0** - fresh worktrees, a from-scratch CRM
      image build, the DB dump restore, and every silent-failure check green. `--verify` also 0
  - [ ] The `git clone` branch is still unexercised: all three repos already existed locally, so
        the run took the worktree path. Only a machine without the clones tests the other half
- [x] Confirmed the `zzz_local_*` initializers load **from the boot log** - both `[local]` lines
      appear under the unicorn pid. They go to `log/development.log` **inside the container**, not
      to `docker compose logs`, which is why the obvious check comes up empty. Now asserted by
      `bootstrap.sh` so it cannot regress silently

### 1.2 Credentials

- [x] `.env.local` (gitignored, chmod 600) holds the credential; `.env.local.example` is the template
- [x] `restore.sh` sources it before resolving `AVANT_ROOT`
- [x] The override declares `AVANT_TEMPLATES_API_KEY` valueless, so Compose passes it through and it
      never lands in a copied file
- [x] Production TemplateFlow key in place 2026-09-02 (`templateflow.boston.k8s.prd.app.avant.com`),
      accepted with 200 on the templates list and reaching the container
- [x] `.env.local` arrived world-readable; chmod 600 applied. It is a production credential

### 1.3 The render path

- [x] Identified the only render path that works locally: `CardmemberAgreementLetter.render_pdf` on
      **stored** `template_variables`. The other two both fail for reasons that never mention the
      agreement (FINDINGS #19)
- [x] Re-extracted the `0122` baseline. **Compare fee content, not bytes** (FINDINGS #20)
- [x] Confirmed 2026-09-02: the **v7 Draft** of template 9658 carries the new fee content, matching
      avant-templates#74 at all five assertion points, with no hardcoded `$28`/`$39` (FINDINGS #21)
- [x] ~~map template **9658** to the uuid basic resolves for `credit_card_cardmember_agreement_1`~~
      **Wrong premise.** 9658 is `5d5b0b5c-...` = `credit_card_cardmember_agreement_consolidated`.
      `_1` is `0b480903-...`, whose newest version is an approved v32 from March with **none** of the
      fee variables. FINDINGS #18 named the wrong render target
- [ ] **Force `show_consolidated_cma?` locally.** Without it a Run renders `_1` and reports
      `$28`/`$39` with no FX paragraph for reasons unrelated to the fee launch: a frontbook code
      that silently passes as backbook (FINDINGS #21)
  - [x] `zzz_local_consolidated_cma.rb` lets the `needs_consolidated_cma` tag past the Optimizely
        guard, per account rather than globally; backed up and wired into `restore.sh`
  - [x] `LocalCmaStub.prepare!` sets the tag, `revert!` drops it, `status` reports both the tag and
        `show_consolidated_cma?`
  - [x] `verify!` refuses to return unless the resolved template is the consolidated one, naming
        the boot-log line to check when it is not
  - [x] Verified on the booted stack 2026-09-02: the prepend sits ahead of `CreditCardAccount`,
        an untagged account reads false, a tagged one flips both `scenario_enabled?` and
        `consolidated_cma_enabled?` to true, and `consolidated_cma_cutoff_date` is confirmed `nil`
  - [x] Proven end to end on account 1: `cma_template` resolves to
        `:credit_card_cardmember_agreement_consolidated`, `show_consolidated_cma` is true, and the
        render picked up the v7 draft content
  - [x] `prepare!` now also backfills the pricing strategy from the decision path tag when the
        CCAPI payload has none - another Fiserv-only field - and reports `strategy_backfilled`
        so the artifact can show that the strategy was supplied rather than read back
- [ ] Assert the resolved template name per Run, and stamp the Template ID **and** Version ID the
      render returns onto the Attempt
- [ ] Assert `preview` is on for every render. If the stack ever becomes `acts_as_prod?`, drafts stop
      rendering **and** documents start persisting to production

### 1.4 The browser walk

- [x] `scripts/apply_harness.py` carries the five silent browser traps as working helpers
- [x] `APPLY_URL` replaced by `apply_url(code)` off `APPLY_BASE`, local by default and
      env-overridable. The local flow accepts the strategy param and reaches `#/personal`
- [x] `STRATEGY_UUIDS` replaced by `load_run_matrix()` / `strategy_uuids()` reading
      `data/run-matrix.csv` - all 16 URL-reachable codes, and MLA codes now raise with the base
      code to apply under instead of building a URL with `strategy=None`
- [x] **Walked `0122` end to end 2026-09-02. All fee assertions PASS.** Application 6 -> account 1,
      decisioned under `0122`, issued with a real Fiserv customer reference, rendered against the
      production v7 draft in preview mode. Evidence in `evidence/run-0122/`
  - [x] `$30` / `$41` late fee sentence, 3% FX paragraph, conversion-rate-costs clause, and the
        summary FX row all present; no stale `$28`/`$39`; the cash-advance `3%` sentence still
        distinct, so the FX check is not a false positive; APR 35.99 as the matrix expects
  - [x] Runbook corrected from what actually happened (FINDINGS #25-28)
  - [ ] Capture `template_version_uuid` per Attempt - the letter path does not expose it
        (FINDINGS #28). The Run above records the template uuid only
  - [ ] Re-walk `0120` (the backbook half of the Pair) for the absence assertions

### 1.5 MLA forcing

Needed in Phase 1: 12 of the 28 codes are MLA variants, and a teammate asking for one today gets
told it is unrunnable.

- [ ] `zzz_local_mla_stub.rb`, patching **only** `raw_test_data`'s `transunion_mla` branch
- [ ] Backed up into `local-stack/` and wired into `restore.sh`
- [ ] Asserts `military_lending_act_confirmed` is true **and** the resolved strategy is the MLA code
- [ ] One MLA Run rendered end to end (`3M33`)

### 1.6 Assertions

- [x] Layer 2 assertions derived from the approved redline into `data/redline-assertions.json`
- [ ] Layer 1 value table, all five assertion points
- [ ] Absence assertions for backbook codes: no FX paragraph, summary row reads `None`
- [ ] Full-sentence matching, so the cash-advance `3%` cannot produce a false pass
- [ ] Assertion failures reported as results, never quietly fixed to make a Run proceed

### 1.7 Done when

- [ ] A teammate with only this repo runs the skill and validates `0122` and `0120` unaided

---

## Phase 2 - remove the LLM from the loop

Replace the browser phase with a deterministic script: raw CDP against a Chrome the script launches
itself, one isolated browser context per Run, no model deciding what to click. Same assertions, same
evidence, zero tokens per Run.

That is what makes the full 28-Run Campaign practical - parallel, unattended, repeatable on every
template change - and what the Manifest, the Attempt log and the resume design in `DESIGN.md` exist
to support.

### 2.1 The CDP port

- [ ] `scripts/apply_harness.py` ported from browser-harness helpers to a standalone CDP client.
      The logic transfers directly: it is already raw CDP calls and JS strings
- [ ] Own Chrome launched on a debug port; the user's browser never touched
- [ ] One `Target.createBrowserContext` per Run - a genuinely separate cookie jar, not shared incognito
- [ ] Stage-change assertion after every step; silent blocks surfaced by blur-then-reread
- [ ] Application id captured explicitly at creation
- [ ] Verified zero tokens consumed per Run

### 2.2 Manifest and provenance

- [x] Manifest schema committed (`data/manifest.schema.json`), so two agents cannot invent two shapes
- [ ] Seeded from `data/run-matrix.csv` with a content hash; refuses to start if the matrix changed
- [ ] Read/write behind a lock, written through on every stage transition
- [ ] Append-only Attempt log; status derived from the newest Attempt
- [ ] Every handle captured by explicit id. **Audit for `.last` and remove every one**
- [ ] `LocalCmaStub.revert!` in a finally-block, so a crashed Run leaves no pinned account
- [ ] Database identity recorded on each Attempt
- [ ] `template_version_uuid`, TemplateFlow host and repo SHAs stamped on every Attempt
- [ ] Epoch derived from `template_version_uuid`, never from a fee amount
- [ ] Attempts under a superseded version auto-marked stale and re-queued

### 2.3 Failure handling and resume

- [ ] Mechanical vs Assertion classification at every failure site
- [ ] Hand-off payload complete (`DESIGN.md` decision 10), including `resume_from`
- [ ] Failure signatures mapped to `FINDINGS.md` entries, quoted by number
- [ ] Resume re-enters at `resume_from` on a bare re-invocation
- [ ] Environment-class failures stop the whole Campaign
- [ ] Interventions recorded on the Attempt and persisted into `local-stack/`

### 2.4 Concurrency

- [ ] Pipeline: bounded browser stage, wide console and assertion stages
- [ ] Measured that concurrency 2 actually beats 1 on this hardware before raising it
- [ ] `--concurrency 1` works as a clean-reproduction fallback
- [ ] A halted Run does not stall the others

### 2.5 The artifact

- [ ] `artifact-design` skill loaded before writing it
- [ ] Pair-first layout, headline verdict, evidence behind toggles
- [ ] Shows template version, host, repo SHAs, `mla_forced` and Interventions per Run
- [ ] Draft renders visibly distinguished from approved ones
- [ ] Regenerated after every Run, not only at the end

### 2.6 The Campaign

- [ ] `0122` / `0120` Pair green end to end
- [ ] CSRV-5300's four Pairs green
- [ ] All 28 Runs attempted; every non-pass has a recorded reason
- [ ] Artifact published and handed to product

---

## Sequencing

Phase 1 first, and prove it on a real Run. Do not package or automate a path that has not been
walked - most of the cost of this project so far came from assuming a documented path existed.

---

## Open items not owned by any ticket

- [ ] File the one-line `raw_test_data` defect in `avant-basic` (FINDINGS #3). It blocks the six
      backbook MLA Runs too, so no other dependency resolves it
- [ ] `roll_pricing_strategy_configuration` still rolls 100% to `0120`, so no application is ever
      *organically* assigned a frontbook code. Does not block URL-driven testing. Flagged on CSRV-5297
- [ ] CSRV-5823 tracks the deferred prd Confetti promotion
- [x] ~~Verify Ocala has avant-templates#74's sha synced~~ **Moot.** File-backed templates ship after
      the fee launch, so there is nothing to sync and no `git_sha_version` anywhere. Runs render the
      latest production draft instead
