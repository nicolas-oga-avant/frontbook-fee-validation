"""Run every code in data/run-matrix.csv that still needs it - one script call for the Campaign,
not one per code.

    python3 scripts/run_campaign.py                    # every code, skip what's already passed
                                                        # (seeds data/manifest.json first if it
                                                        # does not exist yet - nothing to lose)
    python3 scripts/run_campaign.py --dry-run           # show the plan, run nothing
    python3 scripts/run_campaign.py --codes 0122,0120   # just these, still in dependency order
    python3 scripts/run_campaign.py --ticket CSRV-5300  # just this ticket's Pair(s)
    python3 scripts/run_campaign.py --concurrency 2     # 2 Pairs in flight at once

Wraps scripts/run_validation.py (ROADMAP 2.1-2.2), one subprocess per code, in the order that
respects the one real dependency between codes: schumer_box_apply's absence checks on a backbook
code only have teeth with its frontbook sibling's capture on disk as --control
(run_validation.py's run_schumer_box_apply), so every pair runs frontbook before backbook.

Concurrency (ROADMAP 2.4): the unit of concurrency is the Pair, not the code, because that
frontbook-before-backbook dependency is real and intra-pair. Each Pair's codes run sequentially,
in a single worker; --concurrency N bounds how many Pairs' worker threads run at once via
concurrent.futures.ThreadPoolExecutor (threads, not processes: the actual work happens in a
subprocess per code, so the GIL is irrelevant - this only bounds how many run_validation.py
subprocesses, and therefore how many browser instances via apply_driver.py, are alive at once).
--concurrency 1 (the default) submits the same Pairs in the same relative order as the flat
code list below, so a single worker thread drains them in that exact order - byte-for-byte the
same schedule as before concurrency existed, which is what ROADMAP 2.4's "clean-reproduction
fallback" requires. A halted or failed code does not stall other Pairs: each Pair's lane is an
independent future that keeps going to its own next code on a non-zero exit (matching
DESIGN.md decision 10 - only environment-class failures are meant to stop everything, and
distinguishing that from an isolated halt is ROADMAP 2.3, unstarted), and other lanes' futures
are scheduled independently regardless of one lane's outcome.

A code already passed on cma + predecisioned_terms + schumer_box_apply (or schumer_box_apply
not_applicable, MLA-forced) is skipped, per data/manifest.json - this is what makes re-invoking
after fixing one code cheap instead of re-walking all 28. Template-Version-aware staleness
(ROADMAP 2.2's "Attempts under a superseded version auto-marked stale") is not built, so a passed
Attempt is trusted at face value here exactly as SKILL.md's bare-invocation rule already does.
"""

import argparse
import csv
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import manifest as manifest_mod          # noqa: E402

MATRIX = os.path.join(_ROOT, "data", "run-matrix.csv")

_DONE_STATUSES = {"passed", "not_applicable"}

_print_lock = threading.Lock()


def _ordered_codes(ticket_filter=None, code_filter=None):
    """Frontbook before backbook, within each Pair, in run-matrix.csv order. Returns the flat
    (code, row) list plus a pair_id per code (the frontbook code of that Pair), so callers can
    group consecutive same-pair_id entries into one concurrency lane."""
    rows = list(csv.DictReader(open(MATRIX, encoding="utf-8")))
    by_code = {r["code"]: r for r in rows}
    ordered = []
    pair_id = {}
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
                pair_id[code] = frontbook
    if code_filter:
        wanted = set(code_filter)
        ordered = [(c, r) for c, r in ordered if c in wanted]
    return ordered, pair_id


def _lanes(codes, pair_id):
    """Group an ordered code list into lanes of consecutive same-Pair codes, preserving order -
    the concurrency unit. A lane with one code (e.g. --codes selected only one side of a Pair)
    is just a lane of length 1."""
    lanes = []
    for code in codes:
        pid = pair_id[code]
        if lanes and lanes[-1][0] == pid:
            lanes[-1][1].append(code)
        else:
            lanes.append((pid, [code]))
    return [codes_ for _, codes_ in lanes]


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


def _run_one(code, forwarded):
    start = time.monotonic()
    with _print_lock:
        print("----- START %s -----" % code)
    r = subprocess.run(
        [sys.executable, os.path.join(_HERE, "run_validation.py"), code] + forwarded)
    elapsed = time.monotonic() - start
    with _print_lock:
        print("----- DONE  %s: %s (%.0fs) -----" % (
            code, "PASS" if r.returncode == 0 else "FAIL/HALT (exit %d)" % r.returncode, elapsed))
    return r.returncode, elapsed


def _run_lane(lane, forwarded):
    """One Pair's codes, sequentially, in this worker. A non-zero exit on one code does not stop
    the rest of the lane (per-code failures are recorded by run_validation.py itself and are not
    this driver's to react to) - it only stops if run_validation.py itself raises, which is a bug
    in the driver, not a Run outcome."""
    out = {}
    for code in lane:
        rc, elapsed = _run_one(code, forwarded)
        out[code] = (rc, elapsed)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--codes", help="comma-separated codes, e.g. 0122,0120 - default: all 28")
    ap.add_argument("--ticket", help="just this ticket's Pair(s), e.g. CSRV-5300")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    ap.add_argument("--force", action="store_true",
                     help="run every selected code even if already passed")
    ap.add_argument("--concurrency", type=int, default=1,
                     help="Pairs to run at once (default 1 - reproduces the pre-concurrency, "
                          "strictly sequential schedule byte-for-byte)")
    ap.add_argument("--password", default=os.environ.get("PASSWORD"))
    ap.add_argument("--headless", action="store_true", default=None)
    ap.add_argument("--branch", default=os.environ.get("VALIDATION_BRANCH", "main"))
    ap.add_argument("--validation-root", default=os.environ.get("VALIDATION_ROOT"))
    ap.add_argument("--compose-project", default=os.environ.get("BASIC_PROJECT"))
    ap.add_argument("--confetti-env", default="dev")
    args = ap.parse_args()

    if args.concurrency < 1:
        print("--concurrency must be >= 1", file=sys.stderr)
        return 1

    if not os.path.exists(manifest_mod.MANIFEST):
        # Safe unconditionally, --force or not: nothing exists yet to clobber. Reseeding an
        # EXISTING manifest is a different, deliberate act (drops every recorded Attempt,
        # AGENTS.md hard rule 1) and stays behind `manifest.py seed --force`, never a side
        # effect of running the Campaign - --force here still only means "ignore already
        # passed" (line ~166), nothing more.
        print("%s missing - seeding from %s" % (manifest_mod.MANIFEST, MATRIX))
        manifest_mod.seed(compose_project=args.compose_project or "basic-frontbook-fee-validation")

    code_filter = args.codes.split(",") if args.codes else None
    plan, pair_id = _ordered_codes(ticket_filter=args.ticket, code_filter=code_filter)
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

    lanes = _lanes(to_run, pair_id)
    print("\n%d of %d codes selected to run, in %d lane(s), concurrency %d%s" % (
        len(to_run), len(plan), len(lanes), args.concurrency,
        " (dry run - nothing executed)" if args.dry_run else ""))
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

    campaign_start = time.monotonic()
    results = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(_run_lane, lane, forwarded) for lane in lanes]
        for f in as_completed(futures):
            results.update(f.result())
    campaign_elapsed = time.monotonic() - campaign_start

    print("\n===== Campaign summary (concurrency %d, %.0fs wall) =====" % (
        args.concurrency, campaign_elapsed))
    for code in to_run:
        rc, elapsed = results[code]
        print("%-6s %s (%.0fs)" % (code, "PASS" if rc == 0 else "FAIL/HALT (exit %d)" % rc,
                                    elapsed))
    print()
    manifest_mod.report()

    return 0 if all(rc == 0 for rc, _ in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
