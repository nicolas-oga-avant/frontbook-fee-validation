"""One script call for a Run: apply -> approve/issue/render -> assert -> record.

Chains five pieces that already work independently and were each verified live on their own:

    scripts/run_apply_standalone.py   apply, zero browser-harness calls (ROADMAP 2.1)
    scripts/console_runner.rb         approve/issue/render, inside the basic container, unchanged
    scripts/assert_value_table.py     the five-point value table, --json
    scripts/assert_schumer_box.py     the account-opening Schumer box, captured mid-apply for free
    scripts/manifest.py record        durable per-Surface status

    python3 scripts/run_validation.py 0122
    python3 scripts/run_validation.py 7M83 --branch mp

Only wires already-verified pieces together and makes no pass/fail decision of its own (hard
rule 2 in AGENTS.md): a FAIL or an uncaptured point from assert_value_table.py is recorded
exactly as reported, never retried or reinterpreted. A raised exception anywhere in the apply or
console phase is a Mechanical Failure by definition - it is recorded `halted`, not silently
swallowed, and always re-raised to the caller (assume silence means failure).

Also auto-records `schumer_box_basic` and `schumer_box_landing` every Run - not from a hardcoded
assumption, but from a live HTTP probe of each surface's own URL (apply_harness.py's
surface_urls()), because both surfaces' "blocked" status is conditional, not a platform constant:
`schumer_box_basic` blocks only because this repo runs off `main` (FINDINGS #35 - the route is
`mp`-only, and already has a proven checker there), and `schumer_box_landing` blocks on two tickets
this repo does not control the shipping of (CSRV-5845/5846). A hardcoded "blocked" would silently
go stale the day either changes - the same silent-failure trap AGENTS.md's central rule warns
about, just aimed at this script's own assumptions instead of the platform's.

Scope: `cma`, `predecisioned_terms` and `schumer_box_apply`, from one applied application.
`predecisioned_terms` IS assert_value_table.py's point "2. Decisioned application" - already
computed here, just recorded under its own name too (surfaces/predecisioned_terms.md).
`schumer_box_apply`'s evidence is a side effect of the apply walk itself
(apply_harness.py's capture_surface, called from apply_driver.py's run_apply()) - this only
asserts what was already captured, nothing new to walk. Not applicable at all to an MLA-forced
code (no strategy uuid, so no Schumer surface exists for it - FINDINGS #8), and for a BACKBOOK
code it only has teeth (assert_schumer_box.py's absence checks) if its frontbook sibling was
already run through this script too, so its capture sits on disk to use as `--control` - a
backbook code run standalone still asserts, honestly, without one and can legitimately come back
`failed` ("unproven") rather than silently skipped.

The two Schumer surfaces this script does NOT touch are `schumer_box_basic` (unreachable on
`main`, FINDINGS #35) and `schumer_box_landing` (blocked on unshipped tickets) - see
.claude/skills/test-frontbook-fee-launch/SKILL.md for what those still need a human/LLM for.

Known, pre-existing incompleteness for a BACKBOOK code's `cma` verdict specifically: Layer 1's
foreign-transaction-absence point is deliberately proven by a separate script
(`assert_cma_absence.py`, `surfaces/cma.md` Step 5's "Absence is a positive assertion"), not by
`assert_value_table.py`. This script only runs the latter, so a backbook code always shows that
one point NOT CAPTURED and its `cma` status comes back `failed` - correctly, per this project's
own rule that an uncaptured point is not a pass, not a regression in this script. Wiring
`assert_cma_absence.py` in too is separate, unstarted work (it needs the same frontbook-sibling-
control pairing `schumer_box_apply` uses above).

Before any of that: a Confetti pre-flight (SKILL.md's "Check Confetti first") checks the code's
uuid resolves and its `basic.pricing_strategy` entry exists, in ~1s and no browser, and halts with
a clear message if not. `Avant::Env::Confetti.confetti_env` defaults to `prd`, only
`.env.development` sets `dev`, so a stack that somehow reads `prd` sees a genuinely new code as
unconfigured - without this check that reads as an apply-flow bug half an hour later instead of a
one-line diagnosis before a browser is even launched.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import apply_harness                     # noqa: E402
import manifest as manifest_mod          # noqa: E402
import redline_text                      # noqa: E402
import run_apply_standalone              # noqa: E402

CONFETTI_BASE = os.environ.get("CONFETTI_BASE", "https://confetti.boston.k8s.prd.app.avant.com")


class RunFailed(Exception):
    """A Mechanical Failure at some named stage - always re-raised, never swallowed."""

    def __init__(self, stage, message):
        super().__init__("[%s] %s" % (stage, message))
        self.stage = stage
        self.message = message


def _confetti_config(path, env, timeout):
    url = "%s/config?path=%s&env=%s" % (CONFETTI_BASE, path, env)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())["config"]
    except Exception as e:
        raise RunFailed("confetti", "could not read %s: %s: %s" % (path, type(e).__name__, e))


def confetti_preflight(code, row, env="dev", timeout=10):
    """SKILL.md's "Check Confetti first", run automatically: fail in ~1s, no browser, on the
    trap that produces a green run validating nothing - a code Confetti does not resolve reads
    exactly like a genuine apply-flow bug otherwise, half an hour and a full Chrome+Rails cycle
    later. An MLA-forced code has no uuid and no basic.pricing_strategy entry of its own by
    design (SKILL.md) - this checks its mla_base_code's instead.
    """
    base_code = row.get("mla_base_code") or code
    base_row = redline_text.load_row(base_code) if base_code != code else row
    uuid = base_row.get("uuid")
    if not uuid:
        raise RunFailed("confetti", "no uuid for %s (or its mla_base_code %s) in "
                                     "run-matrix.csv - cannot preflight Confetti"
                                     % (code, base_code))

    param_to_id = _confetti_config(
        "basic.pricing_strategy.pricing_strategy_param_to_id", env, timeout)
    resolved = param_to_id.get(uuid)
    if resolved != base_code:
        raise RunFailed("confetti",
            "pricing_strategy_param_to_id maps uuid %s to %r, not %r, under env=%s - stale or "
            "unpromoted config (Avant::Env::Confetti.confetti_env defaults to prd; only "
            ".env.development sets dev - confirm that before concluding this Run failed)"
            % (uuid, resolved, base_code, env))

    pricing_strategy = _confetti_config("basic.pricing_strategy", env, timeout)
    if base_code not in pricing_strategy:
        raise RunFailed("confetti", "no basic.pricing_strategy entry for %r under env=%s - "
                                     "stale or unpromoted config" % (base_code, env))

    return {"uuid": uuid, "base_code": base_code, "env": env}


def _probe_reachable(url, timeout=5):
    """True if `url` renders something, False if it 404s - the only two answers that mean
    anything here. Anything else (connection refused, timeout, a 500) raises RunFailed: the
    stack being unreachable is not evidence that a surface is unbuilt, and must not be read as
    one."""
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise RunFailed("schumer_probe", "%s answered HTTP %d (not 404) - check manually"
                         % (url, e.code))
    except Exception as e:
        raise RunFailed("schumer_probe", "could not reach %s: %s: %s"
                         % (url, type(e).__name__, e))


_STATIC_SCHUMER_SURFACES = (
    # (manifest surface name, apply_harness.surface_urls() key, blocked_on if 404)
    ("schumer_box_basic", "schumer_basic", ["dev-mp-only, see FINDINGS #35"]),
    ("schumer_box_landing", "schumer_landing", ["CSRV-5845", "CSRV-5846"]),
)


def record_static_schumer_surfaces(code, row):
    """schumer_box_basic and schumer_box_landing need no application - just the code's uuid
    (surfaces/schumer_box_basic.md, surfaces/schumer_box_landing.md) - so they are recorded here
    independent of whether apply/console/assert below succeeds. Each is probed live rather than
    assumed: an MLA code is not_applicable (no uuid, FINDINGS #8, decided the same way as
    schumer_box_apply); otherwise a 404 means still blocked (their own doc's tickets), and
    anything else means the route now resolves - which is not a pass, since neither surface has
    a capture/assert step wired into this script yet. That gets `not_implemented`, not a silent
    `blocked`, so the day either ships this stops being wrong on its own rather than needing a
    person to remember to flip it.
    """
    if not row.get("uuid"):
        return {name: ("not_applicable", None) for name, _, _ in _STATIC_SCHUMER_SURFACES}

    urls = apply_harness.surface_urls(code)
    results = {}
    for surface, key, blocked_on in _STATIC_SCHUMER_SURFACES:
        url, _ = urls[key]
        try:
            reachable = _probe_reachable(url)
        except RunFailed as e:
            print("    %s: %s - not recorded this Run" % (surface, e.message))
            continue
        if reachable:
            print("    %s: %s now resolves (not a 404) - needs implementing, not just "
                  "recording (see surfaces/%s.md)" % (surface, url, surface))
            results[surface] = ("not_implemented", None)
        else:
            results[surface] = ("blocked", blocked_on)
    return results


def _slug(branch):
    """Same rule as local-stack/branch-env.sh's VALIDATION_SLUG - kept in sync by hand since
    that file is bash and this is the one Python caller that needs the same answer."""
    if branch == "main":
        return ""
    return "-" + re.sub(r"[^a-z0-9-]+", "-", branch.lower())


def _extract_json_block(text, start, end):
    m = re.search(re.escape(start) + r"\n(.*?)\n" + re.escape(end), text, re.S)
    return json.loads(m.group(1)) if m else None


def _docker_compose(project, cwd, *args):
    cmd = ["docker", "compose", "-p", project] + list(args)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def run_console_phase(code, application_uuid, mla_base_code, project, avant_basic_dir):
    local_console = os.path.join(_HERE, "console_runner.rb")
    r = _docker_compose(project, avant_basic_dir, "cp", local_console,
                        "web:/usr/src/app/tmp/console_runner.rb")
    if r.returncode != 0:
        raise RunFailed("console", "could not copy console_runner.rb into the container: %s"
                         % (r.stderr or r.stdout))

    args = [code, application_uuid] + ([mla_base_code] if mla_base_code else [])
    r = _docker_compose(project, avant_basic_dir, "exec", "-T", "web", "bundle", "exec",
                        "rails", "runner", "/usr/src/app/tmp/console_runner.rb", *args)
    if r.returncode != 0:
        raise RunFailed("console", "console_runner.rb exited %d - tail:\n%s"
                         % (r.returncode, (r.stderr or r.stdout)[-4000:]))

    result = _extract_json_block(r.stdout, "CONSOLE_RESULT_JSON_START", "CONSOLE_RESULT_JSON_END")
    if result is None:
        raise RunFailed("console", "no CONSOLE_RESULT_JSON block in output - tail:\n%s"
                         % r.stdout[-4000:])
    return result


def collect_evidence(code, console_result, project, avant_basic_dir, evidence_dir):
    os.makedirs(evidence_dir, exist_ok=True)
    files = console_result["provenance"]["files"]
    container_paths = {
        "html": files["html"],
        "provenance": files["provenance"],
        "observations": console_result["observations_file"],
    }
    local_paths = {}
    for key, container_path in container_paths.items():
        dest = os.path.join(evidence_dir, os.path.basename(container_path))
        r = _docker_compose(project, avant_basic_dir, "cp",
                            "web:%s" % container_path, dest)
        if r.returncode != 0:
            raise RunFailed("evidence", "could not copy %s out of the container: %s"
                             % (container_path, r.stderr or r.stdout))
        local_paths[key] = dest
    return local_paths


def run_assertions(code, observations_path, rendered_path, confetti_env):
    cmd = [sys.executable, os.path.join(_HERE, "assert_value_table.py"), code,
           "--observations", observations_path, "--rendered", rendered_path,
           "--confetti-env", confetti_env, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout), r.returncode
    except ValueError:
        raise RunFailed("assert", "assert_value_table.py produced no parseable JSON (exit %d) - "
                                   "stderr:\n%s" % (r.returncode, r.stderr[-4000:]))


def record_result(code, surface, status, attempt=None, blocked_on=None):
    manifest_mod.record(code, surface, status,
                        attempt_json=json.dumps(attempt) if attempt is not None else None,
                        blocked_on=blocked_on)


def run_schumer_box_apply(code, apply_result, row, evidence_dir):
    """Assert the Schumer box apply_driver.py already captured mid-walk. Returns
    (status, detail) - status is "passed" or "failed" (never "not_applicable" here; that is
    decided in main() from the code's row alone, before a browser is even launched)."""
    capture = apply_result.get("schumer_account_opening_capture")
    if capture is None:
        return "failed", {"reason": "apply produced no schumer_account_opening_capture even "
                                     "though the code is not MLA-forced - check apply_driver.py"}

    cmd = [sys.executable, os.path.join(_HERE, "assert_schumer_box.py"), capture["html"],
           "--code", code]
    control_path = None
    if row["role"] != "new":
        sibling = row["replaces_or_replaced_by"]
        candidate = os.path.join(_ROOT, "evidence", "run-%s" % sibling,
                                 "schumer_account_opening_%s.html" % sibling)
        if os.path.exists(candidate):
            control_path = candidate
            cmd += ["--control", control_path]

    r = subprocess.run(cmd, capture_output=True, text=True)
    out_path = os.path.join(evidence_dir, "schumer_box_apply_%s.txt" % code)
    with open(out_path, "w") as fh:
        fh.write(r.stdout + r.stderr)

    return "passed" if r.returncode == 0 else "failed", {
        "capture": capture["html"], "control": control_path,
        "output_file": out_path, "exit_code": r.returncode,
    }


def _status_for(rows):
    return "passed" if all(r["passed"] for r in rows) else "failed"


def _point(report, prefix):
    return next(p for p in report["points"] if p["title"].startswith(prefix))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("code", help="pricing strategy code, e.g. 0122 or 7M83")
    ap.add_argument("--password", default=os.environ.get("PASSWORD") or "Fr0ntbook!Fee2026")
    ap.add_argument("--headless", action="store_true", default=None)
    ap.add_argument("--branch", default=os.environ.get("VALIDATION_BRANCH", "main"))
    ap.add_argument("--validation-root", default=os.environ.get("VALIDATION_ROOT"))
    ap.add_argument("--compose-project", default=os.environ.get("BASIC_PROJECT"))
    ap.add_argument("--confetti-env", default="dev")
    ap.add_argument("--skip-manifest", action="store_true",
                     help="run the full chain but do not write to data/manifest.json")
    ap.add_argument("--check-confetti", action="store_true",
                     help="only run the Confetti pre-flight and exit - no stack, no browser")
    ap.add_argument("--check-schumer-static", action="store_true",
                     help="only probe/record schumer_box_basic and schumer_box_landing and exit "
                          "- no application, no browser")
    args = ap.parse_args()

    slug = _slug(args.branch)
    validation_root = args.validation_root or os.path.expanduser(
        "~/Source/avant/frontbook-validation%s" % slug)
    avant_basic_dir = os.path.join(validation_root, "avant-basic")
    project = args.compose_project or ("basic-frontbook-fee-validation%s" % slug)
    evidence_dir = os.path.join(_ROOT, "evidence", "run-%s" % args.code)

    # Fail fast on a typo'd code before spending a browser walk on it, and settle whether
    # schumer_box_apply even applies - that answer is static (it depends only on whether the
    # code has a strategy uuid, FINDINGS #8), never on how the Run itself goes.
    row = redline_text.load_row(args.code)

    if args.check_confetti:
        # The standalone form of what every real Run already does as its first step (below) -
        # exists so "check Confetti for this code" never has to mean typing curl by hand or
        # reading it out of a doc. No stack, no browser, no manifest write.
        try:
            info = confetti_preflight(args.code, row, env=args.confetti_env)
        except RunFailed as e:
            print("FAILED: %s" % e.message, file=sys.stderr)
            return 1
        print("OK: uuid=%s resolves to %s under env=%s" % (
            info["uuid"], info["base_code"], info["env"]))
        return 0

    if args.check_schumer_static:
        for surface, (status, blocked_on) in record_static_schumer_surfaces(args.code, row).items():
            print("%s -> %s%s" % (
                surface, status, " [%s]" % ",".join(blocked_on) if blocked_on else ""))
            if not args.skip_manifest:
                record_result(args.code, surface, status, blocked_on=blocked_on)
        return 0

    is_mla = not row.get("uuid")
    if is_mla:
        print("code %s is MLA-forced: schumer_box_apply is not_applicable (no strategy uuid, "
              "FINDINGS #8)" % args.code)
        if not args.skip_manifest:
            record_result(args.code, "schumer_box_apply", "not_applicable")

    if not args.skip_manifest:
        print("[static] schumer_box_basic / schumer_box_landing (live probe, no application "
              "needed)...")
        for surface, (status, blocked_on) in record_static_schumer_surfaces(
                args.code, row).items():
            record_result(args.code, surface, status, blocked_on=blocked_on)

    stage = "confetti"
    try:
        print("[1/6] Confetti pre-flight...")
        confetti_info = confetti_preflight(args.code, row, env=args.confetti_env)
        print("    uuid=%s resolves to %s under env=%s" % (
            confetti_info["uuid"], confetti_info["base_code"], confetti_info["env"]))

        stage = "apply"
        print("[2/6] apply (standalone CDP, zero browser-harness calls)...")
        apply_result = run_apply_standalone.run(args.code, args.password,
                                                 headless=args.headless, out_root=None)
        application_uuid = apply_result["application_uuid"]
        mla_base_code = apply_result["apply_code"] if apply_result["mla_forced"] else None
        print("    application_uuid=%s" % application_uuid)

        stage = "console"
        print("[3/6] console: approve, issue, render...")
        console_result = run_console_phase(args.code, application_uuid, mla_base_code,
                                           project, avant_basic_dir)
        print("    credit_card_account_id=%s template_version=%s render_mode=%s"
              % (console_result["credit_card_account_id"],
                 console_result["provenance"]["template_version_id"],
                 console_result["provenance"]["render_mode"]))

        stage = "evidence"
        print("[4/6] pulling evidence out of the container...")
        local = collect_evidence(args.code, console_result, project, avant_basic_dir,
                                 evidence_dir)

        stage = "assert"
        print("[5/6] asserting the value table...")
        report, assert_exit = run_assertions(args.code, local["observations"], local["html"],
                                             args.confetti_env)

        schumer_status, schumer_detail = None, None
        if not is_mla:
            stage = "schumer_box_apply"
            print("[6/6] asserting the Schumer box captured during apply...")
            schumer_status, schumer_detail = run_schumer_box_apply(
                args.code, apply_result, row, evidence_dir)
    except Exception as e:
        # Anything raised by any of the five steps above is a Mechanical Failure by
        # definition - a click that missed, a stack that is down, a container command that
        # failed (AGENTS.md hard rule 2: an Assertion Failure only exists once
        # assert_value_table.py has actually run and reported a value disagreement, which
        # happens after this try block, not inside it). Never swallowed: always re-raised to
        # the caller via a non-zero exit, after being recorded.
        message = e.message if isinstance(e, RunFailed) else "%s: %s" % (type(e).__name__, e)
        print("HALTED at %s: %s" % (stage, message), file=sys.stderr)
        if not args.skip_manifest:
            # All three share this one applied application - a halt before assertion ran
            # denies evidence to all equally. schumer_box_apply is excluded for an MLA code:
            # it was already recorded not_applicable above, independent of how this Run goes,
            # and halted would be a status that disagrees with a fact that never depended on
            # this attempt in the first place.
            surfaces = ["cma", "predecisioned_terms"] + ([] if is_mla else ["schumer_box_apply"])
            for surface in surfaces:
                record_result(args.code, surface, "halted", {
                    "stage": stage,
                    "provenance": {},
                    "failure": {"class": "mechanical", "message": message},
                })
        raise

    # Status is derived from the 25 core assertions only, matching manifest.py's own
    # _derive_status exactly (it never sees RPF - RPF is not part of "assertions" at all here).
    # RPF is "orthogonal to the five" (assert_value_table.py's module docstring) and, per
    # FINDINGS #36, unverifiable on this stack at all - always NOT CAPTURED here, in every Run,
    # by a platform limitation this repo already tracks separately. Folding it into the cma
    # Surface's pass/fail would make manifest.record() reject every attempt-json below with a
    # status-disagreement error (it derives status from `assertions` alone), and would contradict
    # the precedent already in data/manifest.json: prior `passed` Attempts for this same code
    # carry 25/25 with RPF equally uncaptured.
    assertions = [row for point in report["points"] for row in point["rows"]]
    status = _status_for(assertions)

    # predecisioned_terms IS point "2. Decisioned application" (surfaces/predecisioned_terms.md)
    # - same run, same evidence, already computed above. A separate, smaller assertions list and
    # its own (possibly different) status: a bug isolated to the render, say, could leave
    # predecisioned_terms passing while cma fails, or vice versa - each Surface's status must be
    # derived only from its own point, never borrowed from the other's.
    pt_assertions = _point(report, "2.")["rows"]
    pt_status = _status_for(pt_assertions)

    print()
    print("verdict: cma=%s (%d/%d), predecisioned_terms=%s (%d/%d)%s%s" % (
        status, sum(1 for a in assertions if a["passed"]), len(assertions),
        pt_status, sum(1 for a in pt_assertions if a["passed"]), len(pt_assertions),
        " - RPF not verifiable on this stack, FINDINGS #36, does not block either Surface"
        if report["rpf"]["rows"][0]["status"] != "PASS" else "",
        ", schumer_box_apply=not_applicable" if is_mla else
        ", schumer_box_apply=%s%s" % (
            schumer_status,
            " (no --control found for this backbook code - unproven, see output file)"
            if row["role"] != "new" and not schumer_detail.get("control") else "")))

    provenance = {
        "templateflow_host": console_result["provenance"]["templateflow_host"],
        "template_version": console_result["provenance"]["template_version_id"],
        "render_mode": console_result["provenance"]["render_mode"],
    }
    evidence_dir_rel = "evidence/run-%s/" % args.code

    if not args.skip_manifest:
        record_result(args.code, "cma", status, {
            "stage": "asserted", "provenance": provenance, "evidence_dir": evidence_dir_rel,
            "assertions": assertions, "rpf": report["rpf"],
        })
        record_result(args.code, "predecisioned_terms", pt_status, {
            "stage": "asserted", "provenance": provenance, "evidence_dir": evidence_dir_rel,
            "assertions": pt_assertions,
        })
        if not is_mla:
            record_result(args.code, "schumer_box_apply", schumer_status, {
                "stage": "asserted",
                "provenance": {"capture": schumer_detail.get("capture"),
                               "control": schumer_detail.get("control")},
                "evidence_dir": evidence_dir_rel,
                "assertions": [{
                    "label": "schumer_box_apply value table (assert_schumer_box.py)",
                    "passed": schumer_status == "passed",
                    "output_file": schumer_detail.get("output_file"),
                }],
            })
    else:
        print("(--skip-manifest: not recorded)")

    all_passed = status == "passed" and pt_status == "passed" and (
        is_mla or schumer_status == "passed")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
