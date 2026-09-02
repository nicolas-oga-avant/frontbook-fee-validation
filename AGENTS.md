# AGENTS.md - rules of engagement

Read this before touching anything in this workdir. It is short on purpose. The reference behind it
is `FINDINGS.md`; the vocabulary is `CONTEXT.md`; the decisions are `DESIGN.md` and `docs/adr/`.

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
   Mechanical Failures (a click that missed, a stack that is down) are yours to fix. See `DESIGN.md`
   for the split; if you are unsure which one you are looking at, it is an Assertion Failure.
3. **Never render against production TemplateFlow.** Rendering is `POST /documents` - a write. See
   `docs/adr/0001-no-prod-renders-verify-template-sha-instead.md`.
4. **Never commit to the repo checkouts.** They are shared with other agent sessions. All overrides
   are untracked by design and backed up in `local-stack/`. Never switch a checkout's branch to
   accommodate this work.
5. **Never trust a value because it looks plausible.** Cross-check the pricing strategy against the
   application's decision path tag on every Run.

## When you fix something, make it persist

A fix that lives only in a container or a shell history will be rediscovered at full cost by the
next agent. Every Intervention lands in the worktree AND is backed up into `local-stack/`, so
`local-stack/restore.sh` replays it on every future build. Record it on the Attempt so it appears in
the artifact rather than hiding in a directory.

## When you learn something, write it down

`FINDINGS.md` is the most valuable file here. If you burn more than about fifteen minutes on
something that was not documented, that is a finding - add it, with the symptom, the cause, and the
file and line that proves it. Number it and reference the number from failure messages.

## Ticking off work

`ROADMAP.md` carries the objective and the checklist. Tick items as you complete them, in the same commit or
edit as the work itself. Do not tick an item you have not verified end to end. If an item turns out
to be wrong, strike it and say why rather than silently deleting it.

## Where to look

| Question | File |
| --- | --- |
| What am I building, and why is it shaped this way? | `DESIGN.md` |
| What do these words mean? | `CONTEXT.md` |
| How do I get the stack running? | `SETUP.md` |
| What are the steps of one Run? | `PROCEDURE.md` |
| What is broken/surprising about this platform? | `FINDINGS.md` |
| What is the goal, and what is left? | `ROADMAP.md` |
| Why was this decided? | `docs/adr/` |
