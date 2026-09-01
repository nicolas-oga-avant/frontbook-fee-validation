# Validation never renders against production TemplateFlow

Rendering a cardmember agreement is `POST /documents` (`templateflow-engine`,
`lib/templateflow_engine/client/endpoint/create_document.rb`), so every render writes a document
record. Running the 28-Run validation against production TemplateFlow would therefore create
synthetic documents, under customers who do not exist, in a production document store.

We render only against a non-production TemplateFlow instance, and establish production fidelity
with a read: `GET get_template_details` against prod, comparing its `git_sha_version` to the
Template Version the validated render used. The claim becomes "prod serves template sha X, and we
rendered and verified sha X" rather than "we rendered in prod".

## Consequences

- Drift in the TemplateFlow *engine* between instances is not covered by this check. The existing
  `cma:reconcile` rake task (`avant-basic/lib/tasks/cma.rake`) is the intended guard for that class
  of drift.
- No production TemplateFlow API key is ever needed by the validation run.
