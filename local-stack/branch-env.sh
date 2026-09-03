# Resolves the branch under test, and everything that has to be keyed to it.
#
# Sourced by bootstrap.sh and restore.sh. Sets, and never overrides if already set:
#
#   VALIDATION_BRANCH   the branch to validate against. Default `main`.
#   VALIDATION_SLUG     "" for main, "-<branch>" otherwise. Suffixes paths and project names.
#   DEFAULT_VALIDATION_ROOT  suggested checkout root for this branch
#   BASIC_PROJECT / CCAPI_PROJECT / CRM_PROJECT   Compose project names
#
# Why the branch is a variable and not a constant: whether the frontbook fee launch ships
# before, after or alongside MP is not known, so a Run has to be reproducible against either
# trunk. Nothing here decides which is correct - it only makes the choice explicit and keeps
# the two from sharing a checkout, a container or a database volume.
#
# Everything derived from the branch is suffixed, because Compose project names are global:
# two branches under one project name would hand the second checkout a database migrated for
# the first. `main` gets no suffix so existing stacks, volumes and evidence keep working.

VALIDATION_BRANCH="${VALIDATION_BRANCH:-main}"

if [ "$VALIDATION_BRANCH" = "main" ]; then
  VALIDATION_SLUG=""
else
  # Compose project names take [a-z0-9_-] only, and a branch can hold slashes.
  VALIDATION_SLUG="-$(printf '%s' "$VALIDATION_BRANCH" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9-' '-')"
fi

DEFAULT_VALIDATION_ROOT="${DEFAULT_VALIDATION_ROOT:-$HOME/Source/avant/frontbook-validation$VALIDATION_SLUG}"
BASIC_PROJECT="${BASIC_PROJECT:-basic-frontbook-fee-validation$VALIDATION_SLUG}"
CCAPI_PROJECT="${CCAPI_PROJECT:-ccapi-frontbook-fee-validation$VALIDATION_SLUG}"
CRM_PROJECT="${CRM_PROJECT:-crm-frontbook-fee-validation$VALIDATION_SLUG}"
