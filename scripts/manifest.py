"""Read and record the Manifest (data/manifest.schema.json) - the durable, per-Surface record
of every Run.

The point of this file: running one Surface for a code today, and a different Surface for the
same code in a later session, must combine into one picture with nothing more than reading
data/manifest.json. No evidence-directory eyeballing, no re-deriving what already happened.

    python3 scripts/manifest.py seed                          # once, before the first Run
    python3 scripts/manifest.py record 0122 cma passed --attempt-json '{
        "stage": "asserted",
        "provenance": {"templateflow_host": "...", "template_version": "bd8382f5-..."},
        "evidence_dir": "evidence/run-0122/"
    }'
    python3 scripts/manifest.py record 3M33 predecisioned_terms not_implemented
    python3 scripts/manifest.py record 0122 schumer_box_apply blocked \\
        --blocked-on CSRV-5843,CSRV-5844
    python3 scripts/manifest.py report 0122                   # one code, every Surface
    python3 scripts/manifest.py report                        # every Pair

`record` only ever touches the one (code, surface) cell it is given - every other Surface's
status and Attempt history is left exactly as it was. That is what makes "run cma now, run
predecisioned_terms next week" additive rather than something an agent has to reconstruct.

Never hand-edit data/manifest.json. Every write goes through `record` so the append-only Attempt
rule (AGENTS.md rule 1 by another name) cannot be violated by a slipped edit.
"""

import argparse
import contextlib
import csv
import fcntl
import hashlib
import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
MATRIX = ROOT / "data" / "run-matrix.csv"
MANIFEST = ROOT / "data" / "manifest.json"
_LOCK_PATH = ROOT / "data" / "manifest.json.lock"


@contextlib.contextmanager
def _locked():
    """Exclusive lock held across one whole load-modify-save cycle in record() below.

    ROADMAP 2.4's concurrency made this a real bug, not a theoretical one: confirmed 2026-09-10
    that concurrent run_validation.py subprocesses calling record() around the same moment
    silently lose each other's writes (a plain read-modify-write with no locking - the last
    save wins, wholesale, not just on the one cell each call meant to touch). 5 of 8 codes in a
    concurrency-4 batch lost already-computed, already-verified results this way - the browser
    walk succeeded, evidence sits on disk, and the Manifest still says `pending`. Exactly the
    silent failure AGENTS.md's central rule warns about, just aimed at this script's own file
    I/O instead of the platform.

    A sidecar lock file, not a lock on MANIFEST itself: flock is advisory and tied to the
    open file description, and MANIFEST gets fully rewritten (not edited in place) on every
    save, which would let a second process re-open and re-lock a *different* inode than the one
    the first process is holding.
    """
    _LOCK_PATH.touch(exist_ok=True)
    with open(_LOCK_PATH, "r+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)

SURFACES = [
    "cma",
    "predecisioned_terms",
    "schumer_box_basic",
    "schumer_box_apply",
    "schumer_box_landing",
]

_EXPECTED_FIELDS = {
    "expected_late_fee_1": "late_fee_initial",
    "expected_late_fee_2": "late_fee_subsequent",
    "expected_ftf": "foreign_transaction_fee",
    "expected_rpf": "rpf",
    "expected_max_apr": "max_apr",
    "expected_annual_fee_y1": "annual_fee_y1",
    "expected_annual_fee_y2": "annual_fee_y2",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _matrix_sha256():
    return hashlib.sha256(MATRIX.read_bytes()).hexdigest()


def _seeded_from():
    return "data/run-matrix.csv@%s" % _matrix_sha256()


def _empty_surface():
    return {"status": "pending", "attempts": []}


def _run_from_row(row):
    return {
        "code": row["code"],
        "reachability": row["reachability"],
        "strategy_uuid": row["uuid"] or None,
        "expected": {dst: row[src] for src, dst in _EXPECTED_FIELDS.items()},
        "surfaces": {s: _empty_surface() for s in SURFACES},
    }


def seed(force=False, compose_project="basic-frontbook-fee-validation", volume="unknown"):
    """Build data/manifest.json from data/run-matrix.csv. Refuses to clobber an existing one
    unless --force - reseeding drops every recorded Attempt, which is exactly what AGENTS.md
    rule 1 exists to prevent happening by accident."""
    if MANIFEST.exists() and not force:
        raise SystemExit(
            "%s already exists. Pass --force to reseed - this DROPS every recorded Attempt. "
            "If the matrix changed and you just want the new expected values picked up, do "
            "that deliberately, not as a side effect." % MANIFEST)

    rows = list(csv.DictReader(open(MATRIX, encoding="utf-8")))
    by_code = {r["code"]: r for r in rows}

    pairs = []
    for row in rows:
        if row["role"] != "old":
            continue
        backbook_code = row["code"]
        frontbook_code = row["replaces_or_replaced_by"]
        frontbook_row = by_code.get(frontbook_code)
        if frontbook_row is None:
            raise SystemExit(
                "%s claims %s replaces it, but %s has no row in %s" %
                (backbook_code, frontbook_code, frontbook_code, MATRIX))
        pairs.append({
            "pair_id": "%s->%s" % (backbook_code, frontbook_code),
            "ticket": row["ticket"],
            "runs": {
                "backbook": _run_from_row(row),
                "frontbook": _run_from_row(frontbook_row),
            },
        })

    doc = {
        "schema": 2,
        "seeded_from": _seeded_from(),
        "database": {"compose_project": compose_project, "volume": volume},
        "pairs": pairs,
    }
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n")
    print("Seeded %s: %d Pairs, %d Runs, %s@%s" %
          (MANIFEST, len(pairs), len(pairs) * 2, MATRIX.name, _matrix_sha256()[:12]))


def _load():
    if not MANIFEST.exists():
        raise SystemExit("%s does not exist. Run `python3 scripts/manifest.py seed` first." %
                          MANIFEST)
    return json.loads(MANIFEST.read_text())


def _save(doc):
    MANIFEST.write_text(json.dumps(doc, indent=2) + "\n")


def _check_seeded_from(doc):
    current = _seeded_from()
    if doc["seeded_from"] != current:
        raise SystemExit(
            "data/run-matrix.csv no longer matches this Manifest's seeded_from "
            "(%s vs %s). The matrix changed since seeding - reseed deliberately "
            "(`seed --force`) rather than recording against a stale expectation set." %
            (doc["seeded_from"], current))


def _find_run(doc, code):
    for pair in doc["pairs"]:
        for role in ("backbook", "frontbook"):
            run = pair["runs"][role]
            if run["code"] == code:
                return run, pair, role
    raise SystemExit("%s is not in the Manifest. Check data/run-matrix.csv and reseed if it "
                      "should be there." % code)


_NO_ATTEMPT_STATUSES = {"blocked", "not_applicable", "not_implemented"}


def _derive_status(attempt):
    """What the Attempt's own data says the status must be, or None if it cannot be derived
    (e.g. an in-progress Attempt with no assertions yet - the caller's status is trusted there).
    Existing to enforce the schema's own rule: status is DERIVED from the newest Attempt, never
    authored independently. A caller passing "passed" alongside a failing assertion is exactly
    the plausible-looking-but-wrong value AGENTS.md hard rule 5 warns about, and this is the one
    place in the whole toolchain positioned to catch it mechanically."""
    failure = attempt.get("failure")
    if failure:
        cls = failure.get("class")
        if cls == "assertion":
            return "failed"
        if cls in ("mechanical", "environment"):
            return "halted"
        return None
    assertions = attempt.get("assertions")
    if assertions:
        return "passed" if all(a.get("passed") for a in assertions) else "failed"
    return None


def record(code, surface, status, attempt_json=None, blocked_on=None):
    """Update exactly one (code, surface) cell. Every other cell in the Manifest is untouched,
    which is what lets a later session's Surface add to an earlier session's without either one
    knowing about the other in advance."""
    if surface not in SURFACES:
        raise SystemExit("%s is not a Surface. Valid: %s" % (surface, ", ".join(SURFACES)))
    if status in _NO_ATTEMPT_STATUSES and attempt_json is not None:
        raise SystemExit(
            "%s carries no Attempt (manifest.schema.json) - nothing ran, so there is nothing to "
            "attach. Drop --attempt-json, or pick a status that reflects an Attempt actually "
            "happening." % status)

    attempt = None
    if attempt_json is not None:
        attempt = json.loads(attempt_json)
        if "stage" not in attempt:
            raise SystemExit("attempt-json must include \"stage\" - see manifest.schema.json")
        if "provenance" not in attempt:
            raise SystemExit(
                "attempt-json must include \"provenance\" - a render with no provenance cannot "
                "be attributed to an Epoch (AGENTS.md hard rule 3)")
        derived = _derive_status(attempt)
        if derived is not None and derived != status:
            raise SystemExit(
                "status '%s' disagrees with what this Attempt's own data derives to ('%s'). "
                "Status is DERIVED from the Attempt, never authored independently - pass the "
                "derived value, or the attempt-json is describing something else than what "
                "actually happened." % (status, derived))

    # Locked from here through the save below: concurrent Runs (ROADMAP 2.4) call record() at
    # overlapping times, and a load-modify-save with no lock lets one process's save silently
    # discard another's - see _locked()'s own docstring for how this was actually caught.
    with _locked():
        doc = _load()
        _check_seeded_from(doc)
        run, pair, role = _find_run(doc, code)
        surf = run["surfaces"][surface]

        surf["status"] = status
        if blocked_on is not None:
            surf["blocked_on"] = blocked_on
        elif status != "blocked":
            surf.pop("blocked_on", None)

        if attempt is not None:
            attempt.setdefault("attempt_id",
                                "%s-%s-%d" % (code, surface, len(surf["attempts"]) + 1))
            attempt.setdefault("started_at", _now())
            surf["attempts"].append(attempt)

        _save(doc)

    print("%s / %s (%s) -> %s%s" % (
        pair["pair_id"], code, role, status,
        " [%s]" % ",".join(blocked_on) if blocked_on else ""))


def _surface_line(name, surf):
    n = len(surf["attempts"])
    if not n:
        status = surf["status"]
        if surf.get("blocked_on"):
            status += " [%s]" % ",".join(surf["blocked_on"])
        return "    %-22s %s" % (name, status)
    last = surf["attempts"][-1]
    passed = [a for a in last.get("assertions", []) if a.get("passed")]
    total = len(last.get("assertions", []))
    detail = "stage=%s" % last["stage"]
    if total:
        detail += " assertions=%d/%d" % (len(passed), total)
    tv = (last.get("provenance") or {}).get("template_version")
    if tv:
        detail += " template_version=%s" % tv
    return "    %-22s %-14s (%d attempt%s, latest: %s)" % (
        name, surf["status"], n, "" if n == 1 else "s", detail)


def report(code=None):
    doc = _load()
    for pair in doc["pairs"]:
        runs = pair["runs"]
        if code and code not in (runs["backbook"]["code"], runs["frontbook"]["code"]):
            continue
        print("%s  (%s)" % (pair["pair_id"], pair["ticket"]))
        for role in ("backbook", "frontbook"):
            run = runs[role]
            print("  %s %s" % (role, run["code"]))
            for s in SURFACES:
                print(_surface_line(s, run["surfaces"][s]))
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("seed", help="build data/manifest.json from data/run-matrix.csv")
    p.add_argument("--force", action="store_true")
    p.add_argument("--compose-project", default="basic-frontbook-fee-validation")
    p.add_argument("--volume", default="unknown")

    p = sub.add_parser("record", help="update one (code, surface) cell")
    p.add_argument("code")
    p.add_argument("surface", choices=SURFACES)
    p.add_argument("status", choices=["pending", "in_progress", "halted", "passed", "failed",
                                       "blocked", "not_applicable", "not_implemented", "stale"])
    p.add_argument("--attempt-json", help="a JSON object matching $defs.attempt in the schema")
    p.add_argument("--blocked-on", help="comma-separated ticket ids, e.g. CSRV-5843,CSRV-5844")

    p = sub.add_parser("report", help="print every Surface's status for one code, or all Pairs")
    p.add_argument("code", nargs="?")

    args = ap.parse_args()
    if args.cmd == "seed":
        seed(force=args.force, compose_project=args.compose_project, volume=args.volume)
    elif args.cmd == "record":
        record(args.code, args.surface, args.status, attempt_json=args.attempt_json,
               blocked_on=args.blocked_on.split(",") if args.blocked_on else None)
    elif args.cmd == "report":
        report(args.code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
