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

**The agreement is not the only surface.** CSRV-5300 asks for the fee disclosure to be verified at
*application* time as well as at issuance, and for screenshots per surface, per strategy:

| Surface | Where | Codes it applies to |
| --- | --- | --- |
| Cardmember agreement (CMA) | rendered letter, production TemplateFlow | all 28 |
| `predecisioned_terms` | avant-basic, post-decision | all 28 - the **only** application-time surface an MLA code has |
| avant-basic Schumer box | `/schumer_box/<uuid>` (dev-mp) | the 8 base codes + 8 predecessors |
| Account-opening Schumer box | the `personal_continued` stage of `/apply?...&strategy=<uuid>` | same - **renders today**; CSRV-5843 + CSRV-5844 add the new amounts, not the box |
| Contentful Schumer landing page | `/credit-card/landing/schumer/<uuid>` | same, once CSRV-5845 + CSRV-5846 ship |

MLA codes have **no UUID**, so no `/schumer_box`, no `/apply?strategy=` and no landing page exists
for them (FINDINGS #8: `param_to_id` carries the 8 base codes only). For an MLA Run the
application-time evidence is `predecisioned_terms` plus the CMA, and that is the ticket's own
instruction, not a shortcut.

RPF is a fourth assertion, orthogonal to all of the above: `$25`, sourced entirely from Optimizely
and never from Confetti (FINDINGS #5), so it needs its own per-Run check rather than a
dependency-table tick.

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
| CSRV-5841 (avant-basic: fee terms into `predecisioned_terms`) | **In Progress** - gates CSRV-5843's data (FINDINGS #34) |
| CSRV-5843 (CAF `SchumerBox.tsx`) | **In Progress** - gates the new amounts in the in-flow box |
| CSRV-5844 (avant-basic `react_index_url` bump to that CAF release) | **Created**, not started - gates delivery, not development (see 1.7) |
| CSRV-5845 (avant-redesign landing-page disclosure) | **In Progress** - gates the Contentful surface |
| CSRV-5846 (Contentful: 8 new landing pages) | **Created**, not started - gates it too |

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
- [x] Confirmed the `zzz_local_*` initializers load **from the boot log** - all three `[local]`
      lines appear under the unicorn pid. They go to `log/development.log` **inside the container**,
      not to `docker compose logs`, which is why the obvious check comes up empty. Now asserted by
      `bootstrap.sh` so it cannot regress silently
  - [x] That assertion was itself broken: `grep | grep -q` under `set -o pipefail` fails once the
        log is large enough, reporting a loaded initializer as missing. Rewritten to read the log
        once and match with `case` (FINDINGS #30)

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
- [x] **Force `show_consolidated_cma?` locally.** Without it a Run renders `_1` and reports
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
- [x] Assert the resolved template name per Run, and stamp the Template ID **and** Version ID the
      render returns onto the Attempt
  - [x] `LocalCmaRender.call!(account, log_id:, expected_code:)` asserts the resolved template by
        name **and** by uuid, so neither a missing `needs_consolidated_cma` tag nor a repointed
        letter config can pass. Backed up and wired into `restore.sh`
  - [x] Stamps the Template ID, the Version ID and `all_version_uuids` into a `provenance.json`
        beside the html and pdf, and refuses a log that already holds a document - `render_pdf`
        returns the stored one and sends no request, so its version id would be a previous
        render's
  - [x] Cross-checks the version on `cardmember_agreement_logs.template_version_id` against the
        one seen on the wire, so a stale column cannot pass for a fresh render
- [x] Assert `preview` is on for every render. If the stack ever becomes `acts_as_prod?`, drafts stop
      rendering **and** documents start persisting to production
  - [x] `zzz_local_render_provenance.rb` refuses a CMA render unless **both** `preview` and
        `allow_unapproved` are on, before the request is sent. `allow_unapproved` was the
        unguarded one and is the more dangerous: without it TemplateFlow serves the newest
        approved version, which has no fee variables (FINDINGS #29)
  - [x] Scoped to the three CMA template uuids - loan contracts render `preview: false`
        legitimately
- [x] **Verified end to end on the booted stack 2026-09-02.** Re-rendered `0122` (account 1,
      log 2): preview and allow_unapproved both true, template `5d5b0b5c-...` consolidated,
      version `bd8382f5-...`, $30/$41/3% present and no stale $28/$39. Every refusal path
      exercised too: preview off, allow_unapproved off, wrong strategy, reused log, foreign log.
      Provenance in `evidence/run-0122/provenance.json`

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
  - [x] ~~Capture `template_version_uuid` per Attempt - the letter path does not expose it
        (FINDINGS #28)~~ **Wrong premise.** It does: `cardmember_agreement_logs` has a
        `template_version_id` column and the letter writes the response's version to it on every
        render. The 0122 Run had recorded `bd8382f5-...` all along. FINDINGS #28 corrected;
        `LocalCmaRender` now reads it back and cross-checks it
  - [x] **Re-walked `0120` end to end 2026-09-02. All absence assertions PASS.** Application 7
        -> account 2, decisioned under `0120` (decision path tag confirms), issued, rendered
        against the **same** template version as `0122` - `bd8382f5-...` - so the whole
        difference between the Pair comes from Confetti, not from the template. Evidence in
        `evidence/run-0120/`
    - [x] Present: the late fee sentence with `$28`/`$39`, the pre-change foreign transactions
          paragraph, `Up to $39` in the summary box
    - [x] Absent: the FX disclosure paragraph, the conversion-rate-costs sentence, `3% of each
          foreign transaction`, and any `$30`/`$41`. Summary Foreign Transaction cell reads
          `None`
    - [x] Every one of the nine checks **flips on the `0122` control**, so none of them is a
          vacuous "did not find it" pass
    - [x] Confetti explains it: `basic.pricing_strategy['0120']` carries no `late_fee_*` and no
          `foreign_transaction_fee` key at all, so the template falls back to its Ruby defaults
          and the FX disclosures stay ungated
  - [x] Four silent browser traps cost four iterations and are now fixed in the harness rather
        than in a transcript: coordinate clicks do nothing on this flow (FINDINGS #31), the
        submit label differs per stage, autofill overwrites the last name the TU mock keys off,
        and the runbook's dashboard approval step never worked locally (FINDINGS #32)

### 1.5 MLA forcing

Needed in Phase 1: 12 of the 28 codes are MLA variants, and a teammate asking for one today gets
told it is unrunnable. It turned out to matter for the other 16 too - see FINDINGS #33.

- [x] ~~`zzz_local_mla_stub.rb`, patching **only** `raw_test_data`'s `transunion_mla` branch~~
      **Wrong target.** The card policy pulls the MLA report through the report manager
      (`pull_using_report_manager?(:transunion_mla)`), so `raw_test_data` never runs on this flow
      and the hardcoded `:mla_negative_stub` blocks nothing. FINDINGS #3 named the wrong method
- [x] The real block is the reverse of the one recorded: `FakeTransunion#get_mla_report` defaults
      **every** applicant to the positive fixture, so locally everyone is a covered borrower.
      Verified on application 7 (`0120`, last name `approved`): MLA confirmed true. 12 of the 16
      URL-reachable codes have an M variant, so each would have silently issued under it
      (FINDINGS #33)
- [x] `zzz_local_mla_stub.rb` dispatches `get_mla_report` on the last name, the way the sibling
      reports already do: `mla` in the name gets the positive fixture, everyone else the negative
      one. `raw_test_data` is patched identically so a non-report-manager policy cannot diverge
  - [x] Both directions verified on the booted stack 2026-09-02: application 9 (`mlaapproved`)
        confirms MLA, application 7 (`approved`) does not. The negative half is what keeps the 16
        base-code Runs honest
- [x] Backed up into `local-stack/` and wired into `restore.sh`, and into `bootstrap.sh`'s
      patch list and boot-log assertion
- [x] Asserts `military_lending_act_confirmed` is true **and** the resolved strategy is the MLA code
  - [x] `LocalMlaStub.verify!(app, expected_code:)` checks the report, `military_lending_act_relevant?`
        and the `code_to_mla` mapping off the decision path tag, reading Confetti's mapping rather
        than a local copy
  - [x] `LocalCmaStub` made MLA-aware: the decision path tag holds the **base** code, so comparing
        it raw against the account's `3M33` failed every MLA Run. It now maps through `code_to_mla`
        when the application is an MLA customer
- [x] **One MLA Run rendered end to end (`3M33`). All fee assertions PASS.** Application 9 ->
      account 3, applied under base `3303` with last name `mlaapproved`, decisioned `3303`, issued
      under `3M33`, rendered against the same production draft as the `0122`/`0120` Pair
      (`bd8382f5-...`). Evidence in `evidence/run-3M33/`
  - [x] `$30`/`$41` late fee sentence, 3% FX paragraph, conversion-rate-costs clause and both
        summary FX rows present; every one of them absent on the `0120` control, so none is a
        vacuous pass. APR 35.99, annual fee $0 year one / $39 after, as the matrix expects
  - [x] The `3M33` config comes from `3303`: `cma_pricing_strategy_config` falls back to
        `code_to_mla.key(identifier)` when the M code has no Confetti entry of its own, which is
        why an MLA account is not quoted backbook fees. That fallback is production code, unpatched
  - [x] A naive "no stale `$39`" check fails on this Run and is a **checker** limitation, not a
        result: `$39` is the year-two annual fee the matrix expects. The late fee sentence is
        pinned whole, so the amount is asserted where it matters

### 1.6 Assertions

- [x] Layer 2 assertions derived from the approved redline into `data/redline-assertions.json`
- [x] `scripts/redline_text.py` owns the redline and the flattening, so a sentence cannot drift
      between the three checkers. `assert_cma_absence.py` was moved onto it and re-run on the
      `0120`/`0122` pair: byte-identical output, so the refactor changed nothing it asserts
- [x] Layer 1 value table, all five assertion points - all five PASS on `0122`, `0120`
      and `3M33` as of 2026-09-03
  - [x] `scripts/assert_value_table.py`, expectations from `run-matrix.csv` and sentences from
        the redline, never a literal. Six points: the five plus RPF
  - [x] The **Confetti** point verified live against dev for **all 28 codes** - fees, apr cap,
        and `param_to_id` or `code_to_mla` per code. Zero failures. The whole config layer of the
        campaign is now proven without a browser
  - [x] The **rendered agreement** point verified on all three existing renders (`0122`, `0120`,
        `3M33`), including the summary box selected by the Run's annual-fee shape rather than
        asserted twice (FINDINGS #10)
  - [x] `local-stack/zzz_local_run_observations.rb` collects the four in-stack points into
        `observations_<code>.json`; wired into `restore.sh`, `bootstrap.sh`'s patch list and its
        boot-log assertion
  - [x] **Exercised on the booted stack 2026-09-03.** The collector ran for `0122`, `0120` and
        `3M33`; all three observations files are in `evidence/run-<code>/observations.json`, and
        **every one of the five points now PASSES on all three Runs** - decision path strategy,
        APR, both annual fees, the three `cma_fee_terms` integers, the five template sites, and
        both CSP labels
  - [x] Two things the first run found. `CustomerApplication`, not `Application`, is the model
        (the collector said so and stopped rather than collecting nothing). And
        `predecisioned_terms[:apr]` is a **fraction** - `"0.3599"` where the matrix quotes
        `35.990` - so the check normalizes anything below 1, no card here being priced under 1%
  - [ ] RPF is the one point that does not answer: **FINDINGS #36**. Optimizely is served from
        `config/optimizely/datafile.json`, revision 1947, whose `card_rpf_fees` audience predates
        this campaign - none of the 28 codes are in it, so every Run reads `false` / `0` / `0`.
        Reported as `NO ANSWER`, which still fails the Run. Needs `OPTIMIZELY_SDK_KEY` on the
        basic container, a change to a shared checkout that was not made here
  - [x] An uncaptured point is not a pass: `NOT CAPTURED` is counted separately from `PASS` and
        fails the Run, because the two are indistinguishable in a summary
- [x] Absence assertions for backbook codes: no FX paragraph, summary row reads `None`
  - [x] `scripts/assert_cma_absence.py`, sentences read from `data/redline-assertions.json`
        rather than copied. Verified on `0120`
  - [x] Takes a `--control` frontbook render and reports any check that passes on both
        documents as `NO TEETH` - an absence check that cannot fail proves nothing
- [x] Full-sentence matching, so the cash-advance `3%` cannot produce a false pass
  - [x] The summary box flattens to labels-then-values, so the Foreign Transaction cell cannot
        be asserted alone. The check pins the whole row, which fixes the cell at `None` *and*
        proves the cash advance sentence is still intact
- [x] Assertion failures reported as results, never quietly fixed to make a Run proceed
  - [x] Both first-pass failures on `0120` were the checker's own patterns, not the document -
        confirmed by reading the flattened text before touching them. The distinction is now in
        the script's docstring, since the output cannot show it
  - [x] Two expectations that look like defects in the checker are recorded as results instead:
        `predecisioned_terms` carries no fee-launch amount (FINDINGS #34), and the standalone
        Schumer box hardcodes the pre-change ones (FINDINGS #35). Both are asserted as they
        actually behave, with the finding named, rather than quietly dropped from the table

### 1.7 The application-time surfaces  (IN PROGRESS)

Everything above validates the CMA - one of the five surfaces CSRV-5300 asks for. The checkers and
the capture now exist; what is missing is a Run that walks them, and two of the three surfaces are
still blocked on their own tickets.

**The two frontbook rows are expected to fail, and that is the point.** CSRV-5843 (in-flow box)
and CSRV-5845 (landing pages) each own one surface and neither has shipped, so an assertion written
today fails today and passes the moment they do. Developing them now is what makes the flip
evidenced rather than asserted. What must never fail for that reason is the `box rendered` guard or
the annual-fee control: those failing means the capture is broken, not the disclosure.

**Read FINDINGS #35 first.** Reading the code answered two of this section's open questions and
turned one of them into a result: `/schumer_box/<uuid>` exists only on `mp`, and where it exists it
hardcodes `Up to $39` and `Foreign Transaction: None` for every strategy. A frontbook capture is
**expected to fail** both fee assertions today.

- [x] Assertion set for the Schumer box derived from the **same** `data/redline-assertions.json`,
      not re-typed. `scripts/assert_schumer_box.py`, asserting only the box whose annual-fee shape
      matches the Run (FINDINGS #10), which `summary_box_for()` derives from the matrix row
  - [x] Frontbook: the `Up to $41` ceiling row and the `3% of each foreign transaction in U.S.
        dollars.` row (Row A governs; Row B is an approved-doc typo)
  - [x] Backbook: `Up to $39` and a Foreign Transaction row reading `None`
  - [x] Every absence check proven to flip on the frontbook control, same `NO TEETH` rule as
        `assert_cma_absence.py`. Exercised against the two CMA summary boxes, which are the same
        disclosure: 4 of 4 discriminate. The first version scored 3 of 4 - a bare `"None" in text`
        passes on a frontbook document that says None anywhere else, so the value is matched
        inside a window after its own row label
  - [x] Refuses an MLA code outright rather than passing while asserting nothing
  - [x] Run against a real capture 2026-09-03 (`0122` and `9004`, account-opening box). The
        checker's assumptions about how the page flattens hold: the box-rendered guard passes and
        both fee checks fail on content, not on a pattern
- [x] **`predecisioned_terms`** read and asserted per Run - but **not for the fees**. It carries no
      foreign transaction fee key at all, and its `maximum_late_fee` is the policy constant `35.0`,
      not the schedule (FINDINGS #34). So the value table asserts what is actually strategy-derived
      there - APR, both annual fees, and the decision path strategy - and pins the `35.0` so the gap
      is recorded on every Run
  - [ ] Product question, not a harness gap: if the applicant is meant to see the new late fee
        before they have an account, this surface cannot currently show it
- [ ] **avant-basic `/schumer_box/<uuid>`** on dev-mp for `0122`, `0123`, `3303`, and $39 / `None`
      still on `0120`, `0121`, `3302`
  - [x] ~~run it on whichever trunk the Run is pinned to and stamp the branch on the evidence~~
        **Resolved, and not by picking one.** The route and `SchumerBoxController` exist on
        `origin/mp` only; `origin/main` has neither. A Run pinned to `main` records the surface as
        unreachable rather than as absent content
  - [x] Confirmed empirically on the running `main` stack 2026-09-03: `/schumer_box/<uuid>`
        returns **404** for the frontbook uuid and for the backbook one alike, and the landing
        page 404s too. `evidence/surface-probe-main.json` records the six probes. A `main` Run
        reports this surface unreachable; it is not evidence about the disclosure
  - [ ] The frontbook half is expected to FAIL when it is finally captured on `mp`: the view
        never reads the three keys CSRV-5298 added. Capture it anyway - the capture is the
        evidence for asking product whether the launch ships with an application-time disclosure
        quoting the old fees
- [x] **Account-opening Schumer box**, same six codes. **Captured and asserted 2026-09-03**, and it
      is a RESULT: both frontbook strategies walked quote `Up to $39` and `Foreign Transaction:
      None` (FINDINGS #35 part three)
  - [x] It is **not** at `/apply?...&strategy=<uuid>`, and it is not blocked. The box is a section
        of the `personal_continued` stage - the same stage that returns `predecisioned_terms` - so
        it renders today on `main` and is reached by walking, not by navigating. What CSRV-5843 and
        CSRV-5844 add is the new content, not the surface
  - [x] `0122` (application 13) and `9004` (application 14) captured, html and png, under
        `evidence/run-<code>/`. The annual fee row differs correctly between them - `$0` versus the
        `$125` introductory text - so the box demonstrably reads the strategy and hardcodes the two
        launch rows anyway. That control is what makes this a defect rather than a mis-walk
  - [x] Two harness gaps this exposed, both fixed: `capture_surface()` navigated by URL and so
        screenshotted the first stage rather than the box (`navigate=False`), and a plain
        screenshot clips the box, which lives in a 240px scroll window over a 740px table, cutting
        off the fee rows (`element="table.schumer-box"` unclips the ancestors and clips the shot to
        the element)
  - [x] The fix site is CAF's `SchumerBox.tsx`, exactly as CSRV-5843 says. An earlier note here
        blamed the `avant_views` HAML partials; those are the legacy Angular renderer and hardcode
        the same rows, but did not render this page (FINDINGS #35). The bundle is pinned by
        `react_index_url` to `micro_frontends/11.4.0`
  - [ ] **Assert against the CAF preview build before CSRV-5844.** Pointing `react_index_url` at
        the preview bundle is the only way to get a pre-deploy pass out of this surface, and it
        turns CSRV-5844 into a delivery step rather than a blocker on validation
  - [ ] Five of the ticket's six not yet walked: `0123`, `3303`, `0120`, `0121`, `3302`. The two
        captured establish the defect; they are not the ticket's per-strategy evidence. `9004` was
        walked as the strategy-sensitivity control, and belongs to CSRV-5303 rather than to this
        six
- [ ] **Contentful landing page** `/credit-card/landing/schumer/<uuid>` agrees with `/apply` for the
      three frontbook codes, per runbook step 15.b. **Blocked on CSRV-5845 + CSRV-5846** - and
      5845's own first acceptance criterion is that 5846 lands first, because all eight pages
      currently 404, which is what this repo's probe already measured
  - [x] CSRV-5845's own preview deploy probed against prod for `0120` and captured under
        `evidence/pr-preview/`. Both are the Gatsby shell with no disclosure in the body, so the
        PR's build changes nothing this campaign can assert yet - the page has to exist first,
        which is CSRV-5846. Kept as the before half of the before-and-after
- [x] `surface_urls(code)` in the harness builds all three URLs per code and names what blocks each,
      off `SCHUMER_BASE` / `LANDING_BASE` so a Run can be pointed at basic-mp without an edit. An
      MLA code gets three `None`s and the reason, not a URL built with `strategy=None`
- [ ] **RPF `$25`** asserted per Run, from a fresh process
  - [x] The value table asserts it against `expected_rpf` from the matrix, and refuses to call a
        read from a stale process a pass - the collector stamps the process age and whether it is a
        console, since the amounts are memoised per account and served from a polled datafile
        (FINDINGS #5)
  - [x] Exercised, and it answered honestly: the datafile is a stale committed snapshot, so the
        point reports `NO ANSWER` with the revision rather than `$0` as a defect (FINDINGS #36)
- [x] A screenshot per surface per strategy, named by Run and surface, stored under
      `evidence/run-<code>/` beside the html and pdf. `capture_surface()` writes the html and the
      png together and indexes both in `surfaces.json` with the URL that produced them - the html
      is what the checkers read, the png is what product signs off on
  - [x] Executed for the account-opening box on `0122` and `9004`; `surfaces.json` in each Run
        directory records the URL, the stage and both files

### 1.8 Branch flexibility - main or mp

Whether the fee launch ships before, after or alongside MP is **not known**, and waiting for that
answer would block everything. So the trunk under test is a parameter, not a constant. FINDINGS #9
argued for `main` and that is still the default - it is what `dev.avant.com/apply` serves - but the
harness no longer assumes it.

- [x] `local-stack/branch-env.sh` derives everything branch-dependent from `VALIDATION_BRANCH`
      (default `main`): the checkout root, and the three Compose project names. `main` stays
      unsuffixed so existing stacks, volumes and evidence keep working
- [x] `bootstrap.sh --branch mp` (or `VALIDATION_BRANCH=mp`), with its own checkout root and its
      own database volume, so the two trunks cannot reshape each other's schema
- [x] Refuses to start when the **other** branch's stack is up. They collide on ports
      5001/7100/4000, not on project name, which Compose reports as an opaque bind failure
- [x] The branch resolves **per repo**, since `credit-card-api` has no `mp`. A repo that falls back
      to `main` is reported rather than failing, and the resolved branch + SHA per repo is written
      to `$VALIDATION_ROOT/.branch-provenance`
- [x] `restore.sh` reads the same resolver, so restoring against an `mp` checkout cannot bring up
      the `main` stack
- [ ] `.branch-provenance` read into the Run evidence, so an artifact says which trunk it proves.
      Written but not yet consumed - a Run is currently branch-flexible and branch-silent
- [ ] The `mp` path actually walked once end to end. Only `main` has been run. Unknowns to expect:
      whether `lib/avant/pricing_strategies/service.rb` exists there (it does not, on the SHA
      FINDINGS #9 checked), and whether the five local patches still apply cleanly
- [ ] `APPLY_BASE` already redirects the browser walk at a remote host, which is how the ticket's
      `dev-mp` surfaces get exercised without a local `mp` stack. Untested against basic-mp
- [ ] A Run's identity includes its trunk: two Runs from different trunks are not comparable, and
      the Campaign must not mix them. Enforce it in the Manifest (2.2) rather than by convention

### 1.9 Done when

- [ ] A teammate with only this repo runs the skill and validates `0122` and `0120` unaided
- [ ] For one Pair, **all five surfaces** captured and asserted, not just the agreement

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
- [ ] Per-Run status is per **surface**, and `data/manifest.schema.json` extended to hold it - the
      schema currently models a single render per Run
- [ ] Read/write behind a lock, written through on every stage transition
- [ ] Append-only Attempt log; status derived from the newest Attempt
- [ ] Every handle captured by explicit id. **Audit for `.last` and remove every one**
- [ ] `LocalCmaStub.revert!` in a finally-block, so a crashed Run leaves no pinned account
- [ ] Database identity recorded on each Attempt
- [ ] `template_version_uuid`, TemplateFlow host and repo SHAs stamped on every Attempt
- [ ] `VALIDATION_BRANCH` and the per-repo resolved branches stamped too, from
      `.branch-provenance`. A Campaign refuses to mix trunks; switching trunk starts a new one
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
- [ ] One row per **surface** per Run, so a Run passing on the CMA and unrun on the Schumer box
      cannot read as green. A blocked surface shows the ticket blocking it
- [ ] Screenshots embedded per surface, since the ticket's sign-off is the screenshots
- [ ] Regenerated after every Run, not only at the end

### 2.6 The Campaign

- [ ] `0122` / `0120` Pair green end to end
- [ ] CSRV-5300's four Pairs green
- [ ] All 28 Runs attempted on every surface that exists for the code; every non-pass has a
      recorded reason, and "surface blocked on CSRV-58xx" counts as recorded, not as passing
- [ ] The four `/apply` and landing-page surfaces re-run after CSRV-5843..5846 deploy
- [ ] Artifact published and handed to product

---

## Sequencing

Phase 1 first, and prove it on a real Run. Do not package or automate a path that has not been
walked - most of the cost of this project so far came from assuming a documented path existed.

---

## Open items not owned by any ticket

- [ ] File the one-line `raw_test_data` defect in `avant-basic` (FINDINGS #3). It is real, but it
      is **not** what blocked the MLA Runs - the card policy never reaches that method (FINDINGS
      #33), so this is now a tidy-up, not a blocker
- [ ] Worth a ticket of its own: `FakeTransunion#get_mla_report` defaulting every applicant to a
      positive MLA report (FINDINGS #33). It is spec-affecting, not just local - any spec that
      pulls an MLA report without pinning an SSN gets a covered borrower it did not ask for
- [ ] `roll_pricing_strategy_configuration` still rolls 100% to `0120`, so no application is ever
      *organically* assigned a frontbook code. Does not block URL-driven testing. Flagged on CSRV-5297
- [ ] CSRV-5823 tracks the deferred prd Confetti promotion
- [x] ~~Verify Ocala has avant-templates#74's sha synced~~ **Moot.** File-backed templates ship after
      the fee launch, so there is nothing to sync and no `git_sha_version` anywhere. Runs render the
      latest production draft instead
