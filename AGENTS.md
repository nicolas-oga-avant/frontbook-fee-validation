# Frontbook fee launch validation

Workdir for the four `[Validation] Frontbook fee launch` tickets (CSRV-5300, 5301, 5302, 5303) under
epic **CSRV-4119** - Late Fee Increase and Introducing Foreign Transaction Fee, frontbook only.

This file is the entry point and the rules of engagement. `README.md` and `CLAUDE.md` are symlinks to
it, so there is one copy and it cannot drift.

**Read all of it before touching anything.** It is short on purpose; every other file is a single
owner of one topic, listed under [Where to look](#where-to-look).

## What this is

A self-sufficient script that runs the end-to-end test proving the fee launch works, so product can
sign off before release. It applies for a card under a given pricing strategy, drives it to
approval, issues it, renders the cardmember agreement, and asserts the fee content - 28 times, in
parallel, unattended, producing a Claude Artifact.

It runs with no parameters. A bare invocation means "advance the Manifest".

The four tickets are **one procedure parameterised by pricing strategy code**. Everything here is
written to be replayed per code, not per ticket. Each ticket's AC 1-3 tests the new strategy; AC 4
tests the old one it replaces ("backbook untouched"). 14 frontbook + 14 backbook = 28, and all 28
are reachable - the 12 MLA variants are forced by a local patch (`DESIGN.md` decision 7), which
earlier notes wrongly recorded as impossible.

This repo is self-contained on purpose: it is cloned onto machines that do not have the wider Avant
platform checkout beside it. That is why the platform context it depends on is restated here and in
`SETUP.md` rather than left to the platform-wide `CLAUDE.md`.

## The one thing to internalise

**Assume silence means failure.** Nearly every failure mode in this domain is silent: a form that
will not submit and renders no error, a decline with a misleading reason, a mock that never
registered, a CMA rendered under the wrong pricing strategy. After every step, assert the state
actually changed. A step that "did not error" has told you nothing.

Two near-misses during discovery would each have produced a green run validating the wrong product:
the canned account stub carries pricing strategy `3007`, and the apply form's AUTOFILL produces a
Miami/FL address with a Chicago ZIP. Both look right.

## Hard rules

1. **Never `.last`.** No `Application.last`, no `cardmember_agreement_logs.issuance.last`, no "the
   most recent account". Runs execute concurrently; every handle is captured by explicit id at the
   moment it is created and threaded through the Manifest. This is the single highest-risk rule
   here, because a contaminated Run produces a plausible wrong answer rather than an error.
2. **Never fix an Assertion Failure.** A rendered value disagreeing with an expected one is a
   *result* - possibly the defect this whole campaign exists to find. Record it and move on.
   Mechanical Failures (a click that missed, a stack that is down) are yours to fix. `CONTEXT.md`
   defines the split; if you are unsure which one you are looking at, it is an Assertion Failure.
3. **Never issue a non-preview render.** Renders go against **production** TemplateFlow, which is
   safe only because `preview: true` keeps them from persisting. Assert preview is on rather than
   assuming it: anything that makes the stack `acts_as_prod?` flips it off silently, and the render
   both stops picking up the draft under test and starts writing to production. See
   `docs/adr/0002-render-drafts-against-production-templateflow.md`.
4. **Never commit to the repo checkouts.** They are shared with other agent sessions. All overrides
   are untracked by design and backed up in `local-stack/`. Never switch a checkout's branch to
   accommodate this work - use a worktree (`SETUP.md`).
5. **Never trust a value because it looks plausible.** Cross-check the pricing strategy against the
   application's decision path tag on every Run.
6. **Test locally.** Dev/Ocala can drive the apply flow but cannot issue a card, so local is the
   only environment where the chain closes.
7. **Work off `main`, not `mp`.** The platform-wide rule is that repos with an `mp` branch base work
   on `mp`, because the multiproduct initiative is the effective trunk. **That rule does not apply
   here.** This is production validation, not MP work: avant-basic#5928 targets `main`, #5927 is the
   `mp` forward-port and off the critical path, and the other three repos have no `mp` branch at
   all. Worktrees track `main`. See `DESIGN.md` decision 4.

## Output conventions

- ASCII punctuation only. No em dashes, en dashes, curly quotes, arrows or ellipsis characters -
  they break copy/paste into terminals and pry (`Encoding::UndefinedConversionError`).
- No emoji in code, comments, or console-bound text.
- No Jira ticket IDs in code comments, `TODO`/`FIXME` included. Ticket context belongs in the commit
  message, the PR description and the ticket. This repo's Markdown is the exception - it is ticket
  documentation, not source.
- Comments are sparse: reasoning behind a non-obvious decision, or a warning that prevents a
  regression. Never a narrative of the work.
- In Jira, PRs, Notion or Slack, link code as a GitHub permalink pinned to a commit SHA with a line
  range, never a bare path or a branch link - these repos move fast and branch links rot. Keep the
  `path:line` form for terminal replies and code comments. Jira's Markdown-to-ADF converter silently
  drops a link whose text contains a backtick code span, so keep Jira link text backtick-free and
  re-read the stored description to confirm.

## When you fix something, make it persist

A fix that lives only in a container or a shell history will be rediscovered at full cost by the
next agent. Every Intervention lands in the worktree AND is backed up into `local-stack/`, so
`local-stack/restore.sh` replays it on every future build. Record it on the Attempt so it appears in
the artifact rather than hiding in a directory.

## When you learn something, write it down

`FINDINGS.md` is the most valuable file here. If you burn more than about fifteen minutes on
something that was not documented, that is a finding - add it, with the symptom, the cause, and the
file and line that proves it. Number it and reference the number from failure messages.

Nothing here needs rediscovering: every stub, override and workaround is already persisted.

## Ticking off work

`ROADMAP.md` carries the objective and the checklist. Tick items as you complete them, in the same
commit or edit as the work itself. Do not tick an item you have not verified end to end. If an item
turns out to be wrong, strike it and say why rather than silently deleting it.

## Where to look

Each file owns its topic. If two files disagree, the owner wins.

| Question | File |
| --- | --- |
| What am I building, and why is it shaped this way? | `DESIGN.md` |
| What do these words mean? | `CONTEXT.md` |
| How do I get the stack running, and what will bite me? | `SETUP.md` |
| What are the steps of one Run? | `.claude/skills/test-frontbook-fee-launch/SKILL.md` |
| What is broken or surprising about this platform? | `FINDINGS.md` |
| What is the goal, what is the current state, what is left? | `ROADMAP.md` |
| Why was this decided? | `DESIGN.md`, `docs/adr/` |

## Layout

```
AGENTS.md      this file - entry point and rules (README.md, CLAUDE.md are symlinks to it)
ROADMAP.md     the objective, the two phases, dependency state, and the checklist
DESIGN.md      what the skill is and why it is shaped this way
SETUP.md       replicable environment setup, the services involved, and the traps
FINDINGS.md    20 platform findings - every failure mode, with evidence
CONTEXT.md     glossary

.claude/skills/test-frontbook-fee-launch/
               SKILL.md - the runbook for one Run; bootstrap.sh - idempotent setup
data/          run-matrix.csv (28 Runs, expected values, UUIDs), redline assertions, source sheet
scripts/       apply_harness.py, extract_redline_assertions.py
local-stack/   the untracked overrides that make the stack work, plus restore.sh
evidence/      captured artifacts; baseline/ holds the verified pre-change 0122 render
reference/     the L&C-approved redline (LGL-7960) - read the .docx, never a PDF export
docs/          ADRs and the apply-flow mock cases
```

Sibling workdir `../CSRV-5667/` holds the Confetti config work that unblocked these.
