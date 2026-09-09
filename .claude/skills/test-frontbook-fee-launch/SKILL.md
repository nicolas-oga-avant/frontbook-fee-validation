---
name: test-frontbook-fee-launch
description: Runs one end-to-end frontbook fee launch validation locally for a given pricing strategy code - sets up the stack from nothing, drives a card application to approval in the browser, issues the card, renders the cardmember agreement, and asserts the fee content. By default it runs every Surface implemented for that code (today, that is the cardmember agreement); pass a Surface name to run just one, e.g. "just check the cma surface for 0122" or "run predecisioned_terms for 3M33". Use when asked to "validate strategy 0122", "test the frontbook fee launch", "run the fee validation for CSRV-5300/5301/5302/5303", to check that a backbook code still renders $28/$39 with no foreign transaction fee, or to check one specific surface (cma, predecisioned_terms, schumer_box_basic, schumer_box_apply, schumer_box_landing). The cma/predecisioned_terms apply-through-render-through-assert-through-record chain runs as one script call (scripts/run_validation.py) with zero browser-harness tool calls; the LLM still picks the code, decides which Surfaces apply, and drives a stage by hand if that script halts. Renders go against production TemplateFlow in preview mode, picking up the latest draft of the template.
---

# Frontbook fee launch validation - one Run

Proves that a card issued under a given pricing strategy shows the right fees on every Surface
CSRV-5300 asks for, not only the cardmember agreement. Epic CSRV-4119: late fee $28/$39 -> $30/$41,
plus a new 3% foreign transaction fee, on frontbook codes only.

**You drive this, but not stage by stage.** Setup is scripted, and as of 2026-09-10 so is the whole
`cma` + `predecisioned_terms` chain: `python3 scripts/run_validation.py <CODE>` runs apply (via
`scripts/run_apply_standalone.py` - its own throwaway Chrome, zero browser-harness tool calls,
ROADMAP 2.1), console (approve/issue/render, `scripts/console_runner.rb`, unchanged), the value-table
assertions and both Surfaces' `manifest.py record` calls, in one call - see `surfaces/cma.md`'s
top note. What is still yours: picking the code, choosing which Surfaces apply, reading the result,
and driving a stage by hand (`surfaces/cma.md` Steps 3-4, or the browser-harness form of the apply
walk) when `run_validation.py` halts - it prints which stage failed and re-raises rather than
guessing. `ROADMAP.md` 2.3 tracks what is still open (failure classification beyond Mechanical vs.
halted, resume); the three Schumer/landing Surfaces are not wired into that script at all.

## Before anything: the one rule

**Assume silence means failure.** Nearly every failure mode here is silent - a form that will not
submit and renders no error, a decline with a misleading reason, a mock that never registered, an
agreement rendered under the wrong strategy. **After every step, assert the state actually changed.**
A step that did not raise has told you nothing.

Two traps that produce a green run validating the wrong product:

- The canned account stub carries pricing strategy `3007`. Always confirm the strategy you asked for.
- `AUTOFILL` produces a Miami/FL address with a Chicago ZIP. Overwrite the whole address.

## Step 1 - Set up

```bash
.claude/skills/test-frontbook-fee-launch/bootstrap.sh
```

Idempotent; `--verify` checks without changing anything. It installs nothing, but it will clone or
add worktrees for `avant-basic`, `credit-card-api` and `crm` under `$VALIDATION_ROOT`
(default `~/Source/avant/frontbook-validation`), restore the local patches, start all three stacks,
and verify the things that fail silently.

### Which branch

`main` by default. Whether the fee launch ships before, after or alongside MP is not settled, so a
Run must be reproducible against either trunk:

```bash
.claude/skills/test-frontbook-fee-launch/bootstrap.sh --branch mp     # or: VALIDATION_BRANCH=mp
```

- A non-`main` branch gets its **own** checkout root (`frontbook-validation-mp`), its own Compose
  projects (`basic-frontbook-fee-validation-mp`) and therefore its own database volume. `main` keeps
  the original unsuffixed names, so existing stacks and evidence are untouched.
- **Only one branch can be up at a time** - both bind ports 5001/7100/4000. Bootstrap detects the
  other branch's stack and tells you what to stop; `down` without `-v` keeps its database, so
  switching back does not re-restore the dump.
- The branch resolves **per repo**: `credit-card-api` has no `mp` branch, so it falls back to `main`
  and bootstrap says so rather than failing. That fallback is usually correct and occasionally the
  reason a Run behaves oddly, so it is written to `$VALIDATION_ROOT/.branch-provenance` and belongs
  on the Run's evidence.
- **Ask the user which branch if they did not say**, and never switch branches mid-Campaign: a Run
  is only comparable to another Run from the same trunk. Read `.branch-provenance` to see where an
  existing checkout actually sits - a directory that already existed was not moved by bootstrap.

It needs one credential: `AVANT_TEMPLATES_API_KEY`, in `.env.local` at the repo root. This is the
**production** TemplateFlow key. If the user does not have one, **ask them** - a teammate can send
their `.env.local`. Do not go looking for it in Vault; it is not there.

Do not proceed on a failed bootstrap. Every one of its checks exists because something downstream
fails silently without it.

## Step 2 - Pick the code and its expectations

Ask the user which pricing strategy code, if they did not say. Then read the row from
`data/run-matrix.csv` - never type expected values from memory.

```bash
python3 - <<'PY'
import csv
CODE = "0122"   # <- the code under test
for r in csv.DictReader(open("data/run-matrix.csv")):
    if r["code"] == CODE:
        print(r)
PY
```

The row gives the strategy UUID, the expected late fees, FX fee, RPF, APR cap, annual fees, the
partner code it replaces, and `reachability`.

`reachability` matters:

- **`direct`** - the code has a UUID and is selectable by URL. 16 of 28.
- **`mla_forced`** - an MLA variant. It has no UUID by design; it is reached by applying under its
  base code (`mla_base_code`) as an applicant the local MLA stub reports as a covered borrower.
  12 of 28. `apply_plan(code)` in the harness returns the URL and the last name to use together -
  use it rather than assembling the two by hand, because a base URL walked with the plain
  `approved` last name produces a Run for the **base** code that looks like an MLA Run.

Confirm the expectations back to the user before spending a browser walk on them.

### Check Confetti first

Cheap, no browser, and it catches a stale-config false failure before a Run is wasted:

```bash
B=https://confetti.boston.k8s.prd.app.avant.com

curl -s "$B/config?path=basic.pricing_strategy.pricing_strategy_param_to_id&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config'].get('$UUID'))"

curl -s "$B/config?path=basic.pricing_strategy&env=dev" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['config']['$CODE'])"
```

`Avant::Env::Confetti.confetti_env` defaults to `prd` (`avant-basic/lib/avant/env.rb:2788`); only
`.env.development` sets `dev`. An app on `prd` does not see the dev-only releases, and the new codes
read as unconfigured. Confirm this before concluding a Run failed.

`mla_forced` codes have no UUID and are not reachable this way. That is by design - check the
`mla_base_code` row instead. The M code carries no `basic.pricing_strategy` entry of its own
either: `cma_pricing_strategy_config` falls back to `code_to_mla.key(identifier)`, so an MLA
account is priced off the base code's entry.

## Choosing which Surface(s) to run

`ROADMAP.md` section 1.7 names five **Surfaces** - the places the fee content must be checked for
one code. A "Run" is not just the agreement; it is every Surface that applies to the code, checked
or explicitly reported as not-yet-checked.

| Surface key | What it is | Applies to | Status | Full procedure |
| --- | --- | --- | --- | --- |
| `cma` | Rendered cardmember agreement, production TemplateFlow | all 28 codes | **Implemented** | `surfaces/cma.md` |
| `predecisioned_terms` | avant-basic, post-decision, before issuance | all 28 codes - the only surface an MLA code has besides the CMA | **Implemented** - discloses neither launch fee (FINDINGS #34) | `surfaces/predecisioned_terms.md` |
| `schumer_box_basic` | `/schumer_box/<uuid>` on dev-mp | the 8 base codes + 8 predecessors (no UUID for MLA codes) | Checker implemented, **unreachable on `main`** (FINDINGS #35) | `surfaces/schumer_box_basic.md` |
| `schumer_box_apply` | `/apply?product_type=credit_card&strategy=<uuid>` | same 16 | **Implemented**, expected to fail until CSRV-5843 + CSRV-5844 ship | `surfaces/schumer_box_apply.md` |
| `schumer_box_landing` | `/credit-card/landing/schumer/<uuid>` | same 16 | **Blocked** on CSRV-5845 + CSRV-5846 | `surfaces/schumer_box_landing.md` |

Each file in the `surfaces/` column is self-contained for that Surface: its own steps (or its own
explicit refusal, if not yet implemented or blocked). Load only the file(s) for the Surface(s) you
are about to run - this file stays the index, not a copy of all five.

### The Manifest is what makes this additive across sessions

`data/manifest.json` (schema: `data/manifest.schema.json`, tooling: `scripts/manifest.py`) is the
per-code, per-Surface record - the thing that makes "run `cma` today, run `predecisioned_terms`
next week" combine into one picture with nothing more than reading a file, rather than an agent
reconstructing what happened by listing `evidence/`.

```bash
python3 scripts/manifest.py seed              # once, the first time this repo's Manifest is used
python3 scripts/manifest.py report <CODE>     # before starting: what's already known about this code
```

After finishing a Surface - pass, fail, or a documented block/non-implementation - record it before
moving on:

```bash
python3 scripts/manifest.py record 0122 cma passed --attempt-json '{
  "stage": "asserted",
  "provenance": {"templateflow_host": "...", "template_version": "<from LocalCmaRender>"},
  "evidence_dir": "evidence/run-0122/",
  "assertions": [...]
}'
python3 scripts/manifest.py record 3M33 predecisioned_terms passed --attempt-json '{"stage": "asserted"}'
python3 scripts/manifest.py record 0122 schumer_box_apply failed --attempt-json '{"stage": "asserted"}'
python3 scripts/manifest.py record 0122 schumer_box_basic blocked --blocked-on "dev-mp-only, see FINDINGS #35"
python3 scripts/manifest.py record 0122 schumer_box_landing blocked --blocked-on CSRV-5845,CSRV-5846
```

`record` touches only the one `(code, surface)` cell named - every other Surface's status and
Attempt history is left exactly as it was. That is the whole mechanism: nothing about running
`predecisioned_terms` next week needs to know what `cma` did this week, because it never touched
`cma`'s cell. **Never hand-edit `data/manifest.json`** - always go through `record`, or the
append-only Attempt rule (AGENTS.md rule 1) can be silently violated by a slipped edit.

**Invocation:**

- **Bare** ("validate 0122", "test the frontbook fee launch for 3M33"): read
  `python3 scripts/manifest.py report 0122` first. If `cma` and/or `predecisioned_terms` is not
  already `passed` under the current Template Version, run `python3 scripts/run_validation.py 0122`
  once - it produces and records both from one applied application (see below). For the three
  Schumer/landing Surfaces (not wired into that script), follow each one's own procedure
  (`surfaces/*.md`) or record `not_applicable`/`not_implemented`/`blocked` by name and, if blocked,
  by ticket. Never silently narrow a full validation down to just the CMA.
- **Scoped** ("just check the cma surface for 0122", "run predecisioned_terms for 3M33", or
  `--surface cma,predecisioned_terms`): if the named Surface is `cma` and/or `predecisioned_terms`,
  `run_validation.py` is what to run either way - the two are produced by one applied application
  and it records both cells from that one run (see below); that is not "recording a Surface nobody
  asked about", it is the same evidence the requested Surface already needed. For any other named
  Surface, run only its own procedure and record only that cell. If a named Surface does not apply
  to the code, is not yet implemented, or is blocked, say so plainly, record that status, and do not
  attempt it - do not improvise steps for a Surface this file has not specified. That is exactly the
  trap hard rule 5 in `AGENTS.md` warns about: a plausible-looking value for a Surface nobody has
  actually verified is worse than an explicit "not run".
- Steps 1-2 above (set up, pick the code) run once regardless of which Surface(s) are selected -
  they are shared prerequisites, not part of any one Surface.
- `cma` and `predecisioned_terms` both need the **same** applied application, and
  `scripts/run_validation.py` is what walks it once and records both cells now - see
  `surfaces/predecisioned_terms.md`. Only fall back to `surfaces/cma.md` Steps 3-4's manual
  per-stage walk when that script halts and something needs to be re-diagnosed by hand. The three
  Schumer/landing Surfaces need no application at all: they are read directly off the code's UUID
  from the matrix row, once implemented.

## Assembling the report across Surfaces

When more than one Surface ran - in this session, in an earlier one, or both - do not hand-combine
a summary. The Manifest already has it, because `record` only ever touched the one cell each
Surface named:

```bash
python3 scripts/manifest.py report <CODE>
```

That is the report: one line per Surface, PASS/FAIL with its Attempt count, **not yet implemented**,
or **blocked** with the ticket(s). Build the user-facing writeup around that output, not instead of
it:

- The overall verdict for the code is the verdict of its `cma` Surface **plus** the full per-Surface
  breakdown - never a bare PASS that quietly means "the agreement was fine". ROADMAP.md 2.5 states
  the artifact-level version of this rule: a Run passing on the CMA and unrun on everything else must
  not read as green.
- If `report` shows a Surface already `passed` under the current Template Version from an earlier
  session, say so and do not re-run it - that is the whole point of recording it durably.
- Note when `cma` and `predecisioned_terms` shared one applied application (see "Choosing which
  Surface(s) to run" above) rather than leaving it implicit that two Surfaces shared one apply -
  this is automatic when `run_validation.py` produced both, but say so anyway.

## If something breaks

`FINDINGS.md` in the repo root documents 38 failure modes with symptom, cause, and the file and line
that proves each. Check it before debugging from scratch - most of what goes wrong here has already
gone wrong once and been written up.

If you hit something genuinely new and it costs more than about fifteen minutes, add it to
`FINDINGS.md`. That file is why this runbook is short.
