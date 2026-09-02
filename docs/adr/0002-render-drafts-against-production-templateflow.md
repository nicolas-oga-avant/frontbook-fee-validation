# Render against production TemplateFlow, in preview mode

**Supersedes an earlier decision that forbade production renders outright** (ADR 0001, since
removed; recoverable from git history).

The earlier reasoning was that rendering is `POST /documents`
(`templateflow-engine/lib/templateflow_engine/client/endpoint/create_document.rb`), and therefore a
write that would leave synthetic documents, under customers who do not exist, in a production
document store. That is true of the general path and false of the one we use.

`avant-templates/app/api/documents.rb:8` documents `preview` as a "Flag to prevent saving a test doc
to prod db", and `app/services/generate_document.rb` returns `id: nil` after calling
`Documents::RenderHtml` - no `Document` row is created. `avant-basic`'s wrapper
(`lib/avant/templateflow/create_document.rb:18-19`) defaults both `preview` and `allow_unapproved` to
`!Avant::Env.acts_as_prod?`, so a local stack already renders in preview mode, and already renders
unapproved drafts.

Two things make production the right target rather than merely an acceptable one:

- **File-backed templates ship after the frontbook fee launch, not before.** The git-backed sync
  (CSRV-5219) is post-launch, so staging has no synced template and no `git_sha_version` to read
  (FINDINGS #18). There is nothing there to validate.
- **The content under test is the draft in production TemplateFlow** (`/templates/9658/edit`). That
  is where it is authored and edited; a copy elsewhere would be validating a different artifact.

## Consequences

- Renders must keep `preview: true`. `allow_unapproved` without `preview` is rejected by TemplateFlow
  anyway (`create_document.rb:23`), so the two travel together - but a change that sets
  `acts_as_prod?` on the validation stack would silently turn both off and begin writing to
  production. Assert `preview` is on rather than assuming it.
- Provenance is the template's **version uuid** from the render response
  (`template_version_uuid`), not a `git_sha_version`, which does not exist yet. Record it on every
  Attempt.
- Validating a *draft* means the artifact must say so. A draft render is not evidence that customers
  receive this content; it is evidence that the pending content is correct.
- A production API key is now required locally. Read-only in effect, but it is a production
  credential: process environment and `.env.local` only, never a versioned file.
