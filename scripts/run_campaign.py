"""Run every code in data/run-matrix.csv that still needs it - one script call for the Campaign,
not one per code.

    python3 scripts/run_campaign.py                    # every code, skip what's already passed
    python3 scripts/run_campaign.py --dry-run           # show the plan, run nothing
    python3 scripts/run_campaign.py --codes 0122,0120   # just these, still in dependency order
    python3 scripts/run_campaign.py --ticket CSRV-5300  # just this ticket's Pair(s)

Wraps scripts/run_validation.py (ROADMAP 2.1-2.2), one subprocess per code, in the order that
respects the one real dependency between codes: schumer_box_apply's absence checks on a backbook
code only have teeth with its frontbook sibling's capture on disk as --control
(run_validation.py's run_schumer_box_apply), so every pair runs frontbook before backbook.

Sequential by design, not yet parallel. ROADMAP 2.4 (concurrency) is unstarted and explicitly
calls for measuring that concurrency 2 beats 1 before raising it - this script is the
`--concurrency 1` fallback that section already anticipates, not a stand-in for that measurement.
Fanning out is a separate, deliberate follow-up once that measurement happens.

A code already passed on cma + predecisioned_terms + schumer_box_apply (or schumer_box_apply
not_applicable, MLA-forced) is skipped, per data/manifest.json - this is what makes re-invoking
after fixing one code cheap instead of re-walking all 28. Template-Version-aware staleness
(ROADMAP 2.2's "Attempts under a superseded version auto-marked stale") is not built, so a passed
Attempt is trusted at face value here exactly as SKILL.md's bare-invocation rule already does.

Does not stop the Campaign on a per-code failure - a FAIL or a HALT is recorded by
run_validation.py itself and this driver moves on to the next code, per DESIGN.md decision 10
("no agent is invited to fix" an Assertion Failure; only environment-class failures should stop
everything). Distinguishing an environment-class HALT from an isolated one is ROADMAP 2.3,
unstarted - this script logs every non-zero exit and keeps going, full stop, and the final
manifest report makes every non-pass visible rather than silently swallowed.
"""

import argparse
import csv
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import manifest as manifest_mod          # noqa: E402

MATRIX = os.path.join(_ROOT, "data", "run-matrix.csv")

_DONE_STATUSES = {"passed", "not_applicable"}


def _ordered_codes(ticket_filter=None, code_filter=None):
    """Frontbook before backbook, within each Pair, in run-matrix.csv order."""
    rows = list(csv.DictReader(open(MATRIX, encoding="utf-8")))
    by_code = {r["code"]: r for r in rows}
    ordered = []
    seen = set()
    for row in rows:
        if row["role"] != "new":
            continue
        if ticket_filter and row["ticket"] != ticket_filter:
            continue
        frontbook, backbook = row["code"], row["replaces_or_replaced_by"]
        for code in (frontbook, backbook):
            if code not in seen:
                seen.add(code)
                ordered.append((code, by_code[code]))
    if code_filter:
        wanted = set(code_filter)
        ordered = [(c, r) for c, r in ordered if c in wanted]
    return ordered


def _needs_run(code):
    """True unless cma + predecisioned_terms + schumer_box_apply are all already settled
    (passed, or not_applicable for schumer_box_apply on an MLA-forced code)."""
    doc = manifest_mod._load()
    run, _, _ = manifest_mod._find_run(doc, code)
    surfaces = run["surfaces"]
    for name in ("cma", "predecisioned_terms", "schumer_box_apply"):
        if surfaces[name]["status"] not in _DONE_STATUSES:
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--codes", help="comma-separated codes, e.g. 0122,0120 - default: all 28")
    ap.add_argument("--ticket", help="just this ticket's Pair(s), e.g. CSRV-5300")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    ap.add_argument("--force", action="store_true",
                     help="run every selected code even if already passed")
    ap.add_argument("--password", default=os.environ.get("PASSWORD"))
    ap.add_argument("--headless", action="store_true", default=None)
    ap.add_argument("--branch", default=os.environ.get("VALIDATION_BRANCH", "main"))
    ap.add_argument("--validation-root", default=os.environ.get("VALIDATION_ROOT"))
    ap.add_argument("--compose-project", default=os.environ.get("BASIC_PROJECT"))
    ap.add_argument("--confetti-env", default="dev")
    args = ap.parse_args()

    code_filter = args.codes.split(",") if args.codes else None
    plan = _ordered_codes(ticket_filter=args.ticket, code_filter=code_filter)
    if not plan:
        print("Nothing matched --ticket/--codes.", file=sys.stderr)
        return 1

    to_run = []
    for code, row in plan:
        needs = args.force or _needs_run(code)
        role = "frontbook" if row["role"] == "new" else "backbook"
        print("%s %-6s %s" % (
            "RUN " if needs else "SKIP",
            code, role + (" (already passed)" if not needs else "")))
        if needs:
            to_run.append(code)

    print("\n%d of %d codes selected to run%s" % (
        len(to_run), len(plan), " (dry run - nothing executed)" if args.dry_run else ""))
    if args.dry_run or not to_run:
        return 0

    forwarded = ["--branch", args.branch, "--confetti-env", args.confetti_env]
    if args.password:
        forwarded += ["--password", args.password]
    if args.headless:
        forwarded += ["--headless"]
    if args.validation_root:
        forwarded += ["--validation-root", args.validation_root]
    if args.compose_project:
        forwarded += ["--compose-project", args.compose_project]

    results = {}
    for i, code in enumerate(to_run, 1):
        print("\n===== [%d/%d] %s =====" % (i, len(to_run), code))
        r = subprocess.run(
            [sys.executable, os.path.join(_HERE, "run_validation.py"), code] + forwarded)
        results[code] = r.returncode

    print("\n===== Campaign summary =====")
    for code, rc in results.items():
        print("%-6s %s" % (code, "PASS" if rc == 0 else "FAIL/HALT (exit %d)" % rc))
    print()
    manifest_mod.report()

    return 0 if all(rc == 0 for rc in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
