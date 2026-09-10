# Frontbook fee launch validation

This repo proves, end to end and mostly unattended, that the frontbook fee launch (CSRV-4119 -
late fee increase, new foreign transaction fee) works correctly across all 28 pricing-strategy
codes it touches, and produces a static HTML report product can open and sign off on.

If you are an AI agent working in this repo, read `AGENTS.md` first - it carries the rules of
engagement, not this file. This file is for a person who wants to run the validation and read
its output.

## Quickstart

1. **Set up the local stack** (Docker, three repos checked out and patched, credentials wired in):

   ```
   .claude/skills/test-frontbook-fee-launch/bootstrap.sh
   ```

   Idempotent - safe to re-run. Needs `.env.local` at the repo root with a production TemplateFlow
   API key (`AVANT_TEMPLATES_API_KEY`) and, to get a real answer instead of "not verifiable on
   this stack" out of any Optimizely-gated assertion, a live `OPTIMIZELY_SDK_KEY` too. Ask a
   teammate for both - neither lives in Vault. See `SETUP.md` for what can go wrong.

2. **Run one code, or all of them:**

   ```
   python3 scripts/run_validation.py 0122              # one code, every applicable Surface
   python3 scripts/run_campaign.py                      # every code that still needs it
   python3 scripts/run_campaign.py --concurrency 4      # the same, several Pairs at once
   ```

   Both are plain Python, no LLM involved. Add `--headless` to skip watching the browser.

3. **Read the report:**

   Every run above regenerates it automatically. Open `report/index.html` in a browser - no
   server needed. To regenerate by hand (e.g. after seeding or editing `data/manifest.json`
   directly), run:

   ```
   python3 scripts/render_report.py
   ```

## What the report shows

One root page, one section per Pair (a frontbook code and the backbook code it replaces), a
strict PASS / NEEDS ATTENTION / INCOMPLETE verdict per Pair, and a detail page per code with
every Surface's evidence - the rendered agreement, the Schumer box captures, every assertion and
why it passed or failed. PASS means every applicable cell on that Pair is `passed`; a cell that
does not apply to a code (e.g. an MLA code has no Schumer box) does not block PASS, but anything
merely unrun, blocked, or genuinely failing does.

## Where to look for more

| Question | File |
| --- | --- |
| What are the rules an agent must follow here? | `AGENTS.md` |
| What is the goal, what is done, what is left? | `ROADMAP.md` |
| What is this validating, and why is it shaped this way? | `DESIGN.md` |
| What do the terms (Run, Pair, Surface, Attempt...) mean? | `CONTEXT.md` |
| How do I get the stack running, and what will bite me? | `SETUP.md` |
| What is broken or surprising about the platform under test? | `FINDINGS.md` |

## Layout

```
scripts/run_validation.py    one code, every applicable Surface, records to data/manifest.json,
                              regenerates the report
scripts/run_campaign.py      run_validation.py fanned out over every code in data/run-matrix.csv
scripts/render_report.py     data/manifest.json + evidence/ -> report/index.html, standalone
scripts/                     the rest: apply_harness.py, assert_*.py, redline_text.py,
                              manifest.py - see AGENTS.md's own layout table for the full list
data/                        run-matrix.csv (28 codes, expected values, UUIDs), manifest.schema.json,
                              redline assertions, manifest.json (the durable per-Surface record)
evidence/                    captured artifacts per run - regenerated, gitignored
report/                      the static site above - regenerated, gitignored
local-stack/                 untracked overrides that make the local stack work, plus restore.sh
reference/                   the L&C-approved redline (LGL-7960)
docs/                        ADRs
.claude/skills/
  test-frontbook-fee-launch/ the manual-fallback runbook for when a script above halts and a
                              stage needs driving by hand - see its own SKILL.md
```
