# Frontbook Fee Validation

The manual end-to-end test that proves the frontbook fee launch (epic CSRV-4119) works
before release: late fee $28/$39 -> $30/$41, plus a newly introduced foreign transaction
fee. This context covers the validation procedure and its evidence, not the fee change
itself.

## Language

**Pricing Strategy Code**:
The four-character identifier of a card pricing configuration (`0122`, `3M33`). The single
parameter the whole procedure varies by.
_Avoid_: strategy, product, plan

**Run**:
One execution of the procedure against one Pricing Strategy Code: apply, approve, issue,
render the agreement, assert.
_Avoid_: test, case, execution

**Pair**:
Two Runs - a new Pricing Strategy Code and the old one it replaces. The unit of evidence:
"backbook untouched" is only expressible across both.
_Avoid_: comparison, delta, couple

**Ticket**:
A CSRV bucket grouping Pairs for reporting. Carries no scope of its own - the procedure and
the manifest span all four tickets.
_Avoid_: scope, batch

**Manifest**:
The durable record of every Run's status, handles and results. The skill's interface: a bare
invocation means "advance the Manifest".
_Avoid_: state file, ledger, queue

**TemplateFlow**:
The service that stores and renders the cardmember agreement. Basic selects an instance with
`AVANT_TEMPLATES_HOST`. Since the CMA templates became git-backed, each stored template carries a
`git_sha_version`.
_Avoid_: avant-templates (that is the repo), template service

**Template Version**:
The `git_sha_version` of the CMA template a Run actually rendered. The provenance stamp that makes
a render's content attributable.
_Avoid_: template revision, draft

**Epoch**:
Which Template Version a Run rendered under, and therefore which expected values apply. Not a
feature flag and not a git branch: the fee content is gated on the presence of Confetti-supplied
variables, so the only thing that changes is the template itself.
_Avoid_: phase, stage, flag state

**Attempt**:
One execution of a Run, stamped with its TemplateFlow instance and Template Version. Runs hold an
ordered list of Attempts; an earlier Attempt is never overwritten.
_Avoid_: retry, try

**Frontbook / Backbook**:
Frontbook is a new Pricing Strategy Code carrying the new fee variables in Confetti. Backbook is
the old code it replaces, which carries none and must render unchanged.
_Avoid_: new/old book, legacy

**Mechanical Failure**:
A break in the test apparatus - a click that missed, a stage that did not advance, a stack that is
down. The agent may diagnose, fix and resume from the failed step.
_Avoid_: error, flake

**Assertion Failure**:
A rendered or resolved value that disagrees with the expected one. A result, never something to be
fixed so the Run can proceed - it may be the defect the campaign exists to find.
_Avoid_: test failure, mismatch

**Intervention**:
A fix an agent applied mid-campaign to resolve a Mechanical Failure, recorded on the Attempt and
surfaced in the artifact. Interventions persist into `local-stack/` so they replay on later builds.
_Avoid_: hack, workaround, patch

**Campaign**:
One pass over the Manifest - the 28 Runs and the artifact they produce.
_Avoid_: suite, batch, session
