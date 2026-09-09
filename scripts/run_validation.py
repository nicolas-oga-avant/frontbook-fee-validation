"""One script call for a Run: apply -> approve/issue/render -> assert -> record.

Chains four pieces that already work independently and were each verified live on their own:

    scripts/run_apply_standalone.py   apply, zero browser-harness calls (ROADMAP 2.1)
    scripts/console_runner.rb         approve/issue/render, inside the basic container, unchanged
    scripts/assert_value_table.py     the five-point value table, --json
    scripts/manifest.py record        durable per-Surface status

    python3 scripts/run_validation.py 0122
    python3 scripts/run_validation.py 7M83 --branch mp

Only wires already-verified pieces together and makes no pass/fail decision of its own (hard
rule 2 in AGENTS.md): a FAIL or an uncaptured point from assert_value_table.py is recorded
exactly as reported, never retried or reinterpreted. A raised exception anywhere in the apply or
console phase is a Mechanical Failure by definition - it is recorded `halted`, not silently
swallowed, and always re-raised to the caller (assume silence means failure).

Scope: `cma` and `predecisioned_terms`, from one applied application - per
surfaces/predecisioned_terms.md, that Surface IS assert_value_table.py's point "2. Decisioned
application", already computed here, just never recorded under its own name until now. The other
three Surfaces (schumer_box_*) are not wired in here - see
.claude/skills/test-frontbook-fee-launch/SKILL.md for what still needs a human/LLM per Surface.
"""

import argparse
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import manifest as manifest_mod          # noqa: E402
import run_apply_standalone              # noqa: E402


class RunFailed(Exception):
    """A Mechanical Failure at some named stage - always re-raised, never swallowed."""

    def __init__(self, stage, message):
        super().__init__("[%s] %s" % (stage, message))
        self.stage = stage
        self.message = message


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


def record_result(code, surface, status, attempt_json, blocked_on=None):
    manifest_mod.record(code, surface, status,
                        attempt_json=json.dumps(attempt_json), blocked_on=blocked_on)


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
    args = ap.parse_args()

    slug = _slug(args.branch)
    validation_root = args.validation_root or os.path.expanduser(
        "~/Source/avant/frontbook-validation%s" % slug)
    avant_basic_dir = os.path.join(validation_root, "avant-basic")
    project = args.compose_project or ("basic-frontbook-fee-validation%s" % slug)
    evidence_dir = os.path.join(_ROOT, "evidence", "run-%s" % args.code)

    stage = "apply"
    try:
        print("[1/4] apply (standalone CDP, zero browser-harness calls)...")
        apply_result = run_apply_standalone.run(args.code, args.password,
                                                 headless=args.headless, out_root=None)
        application_uuid = apply_result["application_uuid"]
        mla_base_code = apply_result["apply_code"] if apply_result["mla_forced"] else None
        print("    application_uuid=%s" % application_uuid)

        stage = "console"
        print("[2/4] console: approve, issue, render...")
        console_result = run_console_phase(args.code, application_uuid, mla_base_code,
                                           project, avant_basic_dir)
        print("    credit_card_account_id=%s template_version=%s render_mode=%s"
              % (console_result["credit_card_account_id"],
                 console_result["provenance"]["template_version_id"],
                 console_result["provenance"]["render_mode"]))

        stage = "evidence"
        print("[3/4] pulling evidence out of the container...")
        local = collect_evidence(args.code, console_result, project, avant_basic_dir,
                                 evidence_dir)

        stage = "assert"
        print("[4/4] asserting the value table...")
        report, assert_exit = run_assertions(args.code, local["observations"], local["html"],
                                             args.confetti_env)
    except Exception as e:
        # Anything raised by any of the four steps above is a Mechanical Failure by
        # definition - a click that missed, a stack that is down, a container command that
        # failed (AGENTS.md hard rule 2: an Assertion Failure only exists once
        # assert_value_table.py has actually run and reported a value disagreement, which
        # happens after this try block, not inside it). Never swallowed: always re-raised to
        # the caller via a non-zero exit, after being recorded.
        message = e.message if isinstance(e, RunFailed) else "%s: %s" % (type(e).__name__, e)
        print("HALTED at %s: %s" % (stage, message), file=sys.stderr)
        if not args.skip_manifest:
            # Both Surfaces share this one applied application (surfaces/predecisioned_terms.md)
            # - a halt before assertion ran denies evidence to both equally.
            for surface in ("cma", "predecisioned_terms"):
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
    print("verdict: cma=%s (%d/%d), predecisioned_terms=%s (%d/%d)%s" % (
        status, sum(1 for a in assertions if a["passed"]), len(assertions),
        pt_status, sum(1 for a in pt_assertions if a["passed"]), len(pt_assertions),
        " - RPF not verifiable on this stack, FINDINGS #36, does not block either Surface"
        if report["rpf"]["rows"][0]["status"] != "PASS" else ""))

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
    else:
        print("(--skip-manifest: not recorded)")

    return 0 if status == "passed" and pt_status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
