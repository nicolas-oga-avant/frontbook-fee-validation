---
name: test-frontbook-fee-launch
description: Runs the frontbook fee launch validation (CSRV-4119) for one pricing strategy code or the whole 28-code campaign. Use when asked to "validate strategy 0122", "test the frontbook fee launch", "run the fee validation", "validate the whole campaign", or to check one specific Surface. One code is one script call (scripts/run_validation.py); every code is one script call (scripts/run_campaign.py) - both are plain Python, zero LLM/browser-harness tool calls, and produce a static HTML report (report/index.html). The LLM's job is picking the code/scope, confirming before a long run, and driving a stage by hand only when a script halts and needs re-diagnosing.
---

# Frontbook fee launch validation

`../../../README.md` (the repo root) is the human-facing doc: what this is, how to run it, how to
read the report. Read that first for the mechanics. This file is the agent-specific layer on top
of it: judgment calls a script does not make, and what to do when one halts.

## Before anything: the one rule

**Assume silence means failure.** Nearly every failure mode here is silent - a form that will not
submit and renders no error, a decline with a misleading reason, a mock that never registered, an
agreement rendered under the wrong strategy. After every step, assert the state actually changed.
A step that did not raise has told you nothing.

Two traps that produce a green run validating the wrong product, if a stage is ever driven by
hand rather than through the scripts: the canned account stub carries pricing strategy `3007` -
confirm the strategy you asked for; `AUTOFILL` produces a Miami/FL address with a Chicago ZIP -
overwrite the whole address.

## Judgment calls a script does not make

- **Which code, and which branch.** Ask the user if they did not say. `main` is the default;
  `mp` only matters for `schumer_box_basic` (FINDINGS #35). Never switch branches mid-Campaign -
  a Run is only comparable to another Run from the same trunk.
- **Confirm before a long run.** `run_campaign.py` over every code is minutes, not seconds -
  confirm with the user before kicking off the full, unfiltered campaign rather than assuming
  "validate everything" means right now. `--dry-run` shows the plan (who's already passed) for
  free.
- **When a script halts, diagnose, do not retry blindly.** `run_validation.py` prints which stage
  failed and re-raises rather than guessing. Read the traceback as the diagnosis. Fall back to
  `surfaces/cma.md`'s manual-walk notes only to re-derive what a halt actually means - not as a
  parallel way to run a Surface that already has a working script path.
- **Never fix an Assertion Failure** (AGENTS.md hard rule 2). A rendered value disagreeing with
  an expected one is a result, not a bug in the harness.

## The five Surfaces

| Surface | What it is | Applies to | Status |
| --- | --- | --- | --- |
| `cma` | Rendered cardmember agreement | all 28 codes | Implemented - `surfaces/cma.md` |
| `predecisioned_terms` | avant-basic, post-decision | all 28 codes | Implemented - `surfaces/predecisioned_terms.md` |
| `schumer_box_apply` | In-flow box, `/apply?...` | 16 direct codes | Implemented - `surfaces/schumer_box_apply.md` |
| `schumer_box_basic` | `/schumer_box/<uuid>`, `mp`-only | 16 direct codes | Implemented, needs `--branch mp` - `surfaces/schumer_box_basic.md` |
| `schumer_box_landing` | Contentful landing page | 16 direct codes | Implemented - `surfaces/schumer_box_landing.md` |

`run_validation.py` decides applicability itself (MLA-forced, route-blocked, route-now-resolved
are all live checks, never assumed) and records every cell in `data/manifest.json` - there is no
Surface-selection logic left for an agent to reason through for a bare "validate `<code>`" ask.
Load a `surfaces/*.md` file only when a Surface's own script path fails and needs re-diagnosing.

## If something breaks

`FINDINGS.md` documents every failure mode found here, with symptom, cause, and the file and line
that proves it. Check it before debugging from scratch. If you hit something genuinely new and it
costs more than about fifteen minutes, add it there - that file is why this skill can stay short.
