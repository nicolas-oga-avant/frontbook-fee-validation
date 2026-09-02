# ROADMAP - the objective, the two phases, and what is left

The single planning document for this project. `DESIGN.md` is how, `AGENTS.md` is the rules,
`FINDINGS.md` is what goes wrong.

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

**Production TemplateFlow**, `https://templateflow.avant.com`, picking up the **latest draft** of the
cardmember agreement template (`/templates/9658/edit`).

No patch is needed for this: `avant-basic/lib/avant/templateflow/create_document.rb:18-19` defaults
both `preview` and `allow_unapproved` to `!Avant::Env.acts_as_prod?`, so a local stack already
renders unapproved drafts, and preview keeps the render from persisting anything. See
`docs/adr/0002`.

File-backed templates ship **after** this launch, so no `git_sha_version` exists anywhere yet
(FINDINGS #18). Provenance is the `template_version_uuid` the render returns.

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
- [x] Refuses to run when a `basic-csrv-5300` stack is already up from another directory, before
      doing any checkout work
- [x] Verifies the silent failures: mock env vars, the key reaching the container, TemplateFlow
      accepting it
- [ ] **Run `bootstrap.sh` end to end on a clean machine.** Only the `--verify` path has been
      exercised; the clone-and-start path has not
- [ ] Confirm the `zzz_local_*` initializers load **from the boot log**, not merely exist on disk

### 1.2 Credentials

- [x] `.env.local` (gitignored, chmod 600) holds the credential; `.env.local.example` is the template
- [x] `restore.sh` sources it before resolving `AVANT_ROOT`
- [x] The override declares `AVANT_TEMPLATES_API_KEY` valueless, so Compose passes it through and it
      never lands in a copied file
- [ ] Swap in a **production** TemplateFlow key - `.env.local` still holds the Ocala staging one

### 1.3 The render path

- [x] Identified the only render path that works locally: `CardmemberAgreementLetter.render_pdf` on
      **stored** `template_variables`. The other two both fail for reasons that never mention the
      agreement (FINDINGS #19)
- [x] Re-extracted the `0122` baseline. **Compare fee content, not bytes** (FINDINGS #20)
- [ ] Confirm the draft at `/templates/9658/edit` carries the new fee content, and map template
      **9658** (a numeric UI id) to the uuid basic resolves for `credit_card_cardmember_agreement_1`
- [ ] Assert `preview` is on for every render. If the stack ever becomes `acts_as_prod?`, drafts stop
      rendering **and** documents start persisting to production

### 1.4 The browser walk

- [x] `scripts/apply_harness.py` carries the five silent browser traps as working helpers
- [ ] Point `APPLY_URL` at the local stack - it still targets `dev.avant.com`
- [ ] Extend `STRATEGY_UUIDS` beyond the four codes it holds, or read `data/run-matrix.csv` directly
- [ ] Walk one Run end to end through the skill, and correct the runbook from what actually happens

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
