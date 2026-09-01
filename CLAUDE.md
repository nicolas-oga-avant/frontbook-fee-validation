# Frontbook fee launch validation

**Read `AGENTS.md` before doing anything.** It carries the rules of engagement and they are not
optional. `README.md` orients; `DESIGN.md` explains why.

This repo is self-contained on purpose: it is cloned onto machines that do not have the wider Avant
platform checkout beside it. What follows is the platform context this work depends on, restated so
it survives the clone.

## Output conventions

- ASCII punctuation only. No em dashes, en dashes, curly quotes, arrows or ellipsis characters -
  they break copy/paste into terminals and pry (`Encoding::UndefinedConversionError`).
- No emoji in code, comments, or console-bound text.
- No Jira ticket IDs in code comments, `TODO`/`FIXME` included. Ticket context belongs in the commit
  message, the PR description and the ticket. This repo's Markdown is the exception - it is ticket
  documentation, not source.
- Comments are sparse: reasoning behind a non-obvious decision, or a warning that prevents a
  regression. Never a narrative of the work.

## The services this touches

| Service | Path | What it does here |
| --- | --- | --- |
| `avant-basic` | `../avant-basic` | Ruby 2.7 / Rails 5.0. Owns the application, decisioning, pricing strategy resolution, and CMA rendering. The centre of this work |
| `credit-card-api` | `../credit-card-api` | Ruby 2.7 / Rails 5.2. Card accounts, onboarding to Fiserv |
| `crm` | `../crm` | TypeScript / React. The CSP admin portal, used for one assertion point |
| `avant-templates` | `../avant-templates` | The TemplateFlow service. Stores and renders the CMA. **Not a gem** - basic talks to it over HTTP |
| `templateflow-engine` | `../templateflow-engine` | The client gem basic uses to reach TemplateFlow |

## Branching

The platform-wide rule is that repos with an `mp` branch base work on `mp`, because the multiproduct
initiative is the effective trunk. **That rule does not apply here.** This is production validation,
not MP work: avant-basic#5928 targets `main`, #5927 is the `mp` forward-port and off the critical
path, and the other three repos have no `mp` branch at all. Worktrees track `main`. See `DESIGN.md`
decision 4.

## Environment facts that will otherwise cost you hours

- **Ocala hosts two Basic deployments**, `basic` and `basic-mp`, with separate databases and disjoint
  data. A customer created in one is invisible in the other. The deployed dev CSP points at
  `basic-mp`. None of this matters while you stay local, which you should.
- **Dev CCAPI points at `basic-mp`** while ocala `basic` points at dev CCAPI, so the dev triangle is
  crossed. Use `Persistence::Customer.local_find`, never `find`, when inspecting dev data.
- **CCAPI stores no customer PII** by design. Do not expect to verify an address there.
- **Dev-utils accounts are not onboarded to Fiserv.** Their `first_data_account_reference` is a
  fabricated Base64 UUID; real ones look like `C26220125456184007040081`. Any FDR call for such an
  account fails with a 500 that says nothing about the code under test.
- **Vault path convention**: `avant/${account_environment}/${service_name}/secrets/<KEY>`, one key
  per sub-path with a single `value` field. Not needed for this work - the one credential involved
  (the TemplateFlow staging API key) is read from a pod's environment, see `SETUP.md`.
- **Non-prod TemplateFlow is `stg`, not `dev`.** The global-dev account's deployment sets
  `environment_override = "stg"`, so anything reasoning about a "dev TemplateFlow" is reasoning
  about something that does not exist.
- **Local basic answers a cold request in ~7s.** Use a generous timeout or a health check will
  conclude it is down when it is merely slow.

`SETUP.md` has the rest, including the traps that produce silent failures.

## Reference code with permalinks

In Jira, PRs, Notion or Slack, link code as a GitHub permalink pinned to a commit SHA with a line
range, never a bare path or a branch link - these repos move fast and branch links rot. Keep the
`path:line` form for terminal replies and code comments.

Jira gotcha: its Markdown-to-ADF converter silently drops a link whose text contains a backtick code
span. Keep Jira link text backtick-free and re-read the stored description to confirm.
