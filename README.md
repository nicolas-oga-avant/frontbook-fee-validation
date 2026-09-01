# Frontbook fee launch validation

Workdir for the four `[Validation] Frontbook fee launch` tickets (CSRV-5300, 5301, 5302, 5303) under
epic **CSRV-4119** - Late Fee Increase and Introducing Foreign Transaction Fee, frontbook only.

The four tickets are **one procedure parameterised by pricing strategy code**. Everything here is
written to be replayed per code, not per ticket.

## What is being built

A self-sufficient script that runs the end-to-end test proving the fee launch works, so product can
sign off before release. It applies for a card under a given pricing strategy, drives it to
approval, issues it, renders the cardmember agreement, and asserts the fee content - 28 times, in
parallel, unattended, producing a Claude Artifact.

It runs with no parameters. A bare invocation means "advance the Manifest".

## Start here

| If you are... | Read |
| --- | --- |
| An agent about to touch anything | **`AGENTS.md`** - rules of engagement, non-negotiable |
| Picking up the build | `TODO.md`, then `DESIGN.md` |
| Setting up a machine | `SETUP.md` |
| Running or debugging one test | `PROCEDURE.md`, then `FINDINGS.md` |
| Confused by a word | `CONTEXT.md` |
| Wondering why something was decided | `DESIGN.md`, `docs/adr/` |

## Layout

```
AGENTS.md      rules of engagement - read first
DESIGN.md      what the skill is and why it is shaped this way
SETUP.md       replicable environment setup
PROCEDURE.md   the steps of one Run
FINDINGS.md    17 platform findings - every failure mode, with evidence
CONTEXT.md     glossary
TODO.md        implementation checklist, ticked as work completes

data/          run-matrix.csv (28 Runs, expected values, UUIDs), redline assertions, source sheet
scripts/       apply_harness.py, extract_redline_assertions.py
local-stack/   the untracked overrides that make the stack work, plus restore.sh
evidence/      captured artifacts; baseline/ holds the verified pre-change 0122 render
reference/     the L&C-approved redline (LGL-7960) - read the .docx, never a PDF export
docs/          ADRs, the run-1 record, the apply-flow mock cases, superseded docs
```

`docs/superseded-*.md` are the pre-restructure `HANDOFF.md` and `TEST-STRATEGY.md`. Kept for
provenance; **do not act on them** - several of their claims are stale, and the corrections are in
`DESIGN.md`.

## Scope: 28 Runs

Each ticket's AC 1-3 tests the new strategy; AC 4 tests the old one it replaces ("backbook
untouched"). 14 frontbook + 14 backbook = 28. All 28 are reachable - the 12 MLA variants are forced
by a local patch (`DESIGN.md` decision 7), which earlier notes wrongly recorded as impossible.

## State as of 2026-09-01

| Dependency | State |
| --- | --- |
| avant-basic#5928 (CSRV-5298, `cma_fee_terms`) | **Merged** 2026-08-28 into `main` |
| avant-templates#74 (CSRV-5299, CMA content) | **Open, draft**, base `main` |
| CSRV-4904 (template extraction to git-backed Liquid) | Merged |
| Confetti `basic.pricing_strategy` (fees) | v17, dev and prd |
| Confetti param-to-id / apr-caps (+8 UUIDs) | dev only; prd promotion deferred to CSRV-5823 |
| Optimizely RPF audience + staging fee amounts | done, both environments |

**There is no `new_fee_structure` feature flag.** It was in CSRV-5299's description and never
existed. Fee content is gated on the *presence* of Confetti-supplied variables. See `DESIGN.md`
decision 5.

The baseline render in `evidence/baseline/` shows $28/$39 and no FX fee. That is **correct** - it is
a verified pre-change render, and it should flip to $30/$41/3% once the new Template Version is live
on Ocala TemplateFlow.

## Ground rules

1. **Test locally.** Dev/Ocala cannot issue a card, so local is the only environment where the chain
   closes.
2. **Nothing here needs rediscovering.** Every stub, override and workaround is persisted.
3. **Do not commit to the repo checkouts.** They are shared with other agent sessions.
4. **Assume silence means failure.** See `AGENTS.md`.

Sibling workdir `../CSRV-5667/` holds the Confetti config work that unblocked these.
