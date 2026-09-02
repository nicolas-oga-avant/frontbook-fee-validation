# ROADMAP - what this project is for

The objective, in two phases. Read `DESIGN.md` for how, `AGENTS.md` for the rules, `TODO.md` for
the checklist.

## The goal

Prove that the frontbook fee launch (epic CSRV-4119) renders correctly on the cardmember agreement,
for every affected pricing strategy, so product can sign off **before** release. 28 Runs: 14
frontbook codes carrying the new fees, and the 14 backbook codes they replace, which must render
unchanged.

The deliverable is evidence, not a green console. Product signs off on an artifact showing the fee
amounts on a real rendered agreement.

## Phase 1 - end-to-end, LLM in the loop  (IN PROGRESS)

A skill that takes a machine from nothing to a validated Run.

- Sets up the three repos locally, applies the local patches, brings the stack up, and verifies the
  things that fail silently.
- Drives the whole account issuance path - apply, approve, issue - through **browser-harness**, with
  the agent deciding what to click.
- Renders the cardmember agreement and asserts the fee content against `data/run-matrix.csv` and the
  approved redline.

Shipped as `.claude/skills/test-frontbook-fee-launch/`. It costs tokens per Run, and that is
accepted for now: the point of Phase 1 is that the whole chain closes and a teammate can run it.

### What Phase 1 renders against

**Production TemplateFlow**, `https://templateflow.avant.com`, rendering the **latest draft version**
of the cardmember agreement template (`/templates/9658/edit`).

This is deliberate and it supersedes the earlier decision to render only against staging:

- **File-backed templates are not shipping until after the frontbook fee launch.** The git-backed
  sync (CSRV-5219) is post-launch work, so there is no synced staging template to test, and no
  `git_sha_version` to read (FINDINGS #18).
- The artifact actually under test **is** the draft in production TemplateFlow. That is where the
  content lives and where it is being edited.
- A preview render does not persist anything - see `docs/adr/0002`.

## Phase 2 - remove the LLM from the loop

Replace the browser phase with a deterministic script: raw CDP against a Chrome the script launches
itself, one isolated browser context per Run, no model deciding what to click. Same assertions, same
evidence, zero tokens per Run.

That is what makes the full 28-Run Campaign practical - parallel, unattended, repeatable on every
template change - and what the Manifest, the Attempt log and the resume design in `DESIGN.md` exist
to support.

`scripts/apply_harness.py` already holds the logic and is already raw CDP calls and JS strings; it
is written against browser-harness's helpers and needs porting to a standalone client. Phase 2 is
mostly that port plus the orchestration around it.

## Sequencing

Phase 1 first, and prove it on a real Run. Do not package or automate a path that has not been
walked - most of the cost of this project so far came from assuming a documented path existed.
