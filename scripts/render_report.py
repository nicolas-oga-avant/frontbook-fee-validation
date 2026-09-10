"""Deterministic static-site report over data/manifest.json - zero LLM, zero tokens, to generate
or to view.

    python3 scripts/render_report.py

Writes report/index.html (one section per Pair, Pair-first per DESIGN.md decision 12) plus
report/codes/<code>/index.html (one section per Surface). Every cross-link is derived from the
Manifest's own pairs[] array - nothing is ever hand-linked, and the whole directory is wiped and
rewritten from scratch on every call, so a code later removed from the matrix never lingers.

Assumes ONE canonical shape everywhere: every recorded assertion is {label, status, expected,
actual, passed}, every recorded provenance is the same six-key envelope (templateflow_host,
template_version, render_mode, mla_forced, capture, control), regardless of which Surface wrote
it. That is a property of the producers (scripts/run_validation.py), not something this script
works around - a KeyError here means a producer regressed the shape and should be loud, not
silently degraded. Only genuinely optional/nullable values (a field that legitimately does not
apply to a given surface) go through fmt().

evidence/run-<code>/ is copied into report/codes/<code>/evidence/, not referenced in place -
evidence/ is gitignored, per-run, regenerable, and can be deleted independently of when a report
is opened. Copying makes report/ a portable, self-contained bundle. The exact render to copy is
located by the recorded handles.cma_log_id, never "the newest file in the directory" - this
script's own version of AGENTS.md hard rule 1.

Called automatically at the end of every scripts/run_validation.py invocation (best-effort - a
failure here never affects that script's real exit code). Also runnable standalone, with no
required args, including against an all-pending Manifest before any Attempt exists.
"""

import html
import json
import os
import shutil
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

import manifest as manifest_mod  # noqa: E402

MANIFEST = os.path.join(_ROOT, "data", "manifest.json")
EVIDENCE_ROOT = os.path.join(_ROOT, "evidence")
OUTPUT_DIR = os.path.join(_ROOT, "report")
SURFACES = manifest_mod.SURFACES

MISSING = "NOT CAPTURED"

EXPECTED_FIELD_LABELS = [
    ("late_fee_initial", "late fee (1st)"),
    ("late_fee_subsequent", "late fee (subsequent)"),
    ("foreign_transaction_fee", "foreign transaction fee"),
    ("rpf", "RPF"),
    ("max_apr", "max APR"),
    ("annual_fee_y1", "annual fee (Y1)"),
    ("annual_fee_y2", "annual fee (Y2)"),
]

PROVENANCE_FIELD_LABELS = [
    ("templateflow_host", "TemplateFlow host"),
    ("template_version", "Template version"),
    ("render_mode", "Render mode"),
    ("mla_forced", "MLA forced"),
    ("capture", "Capture"),
    ("control", "Control (--control sibling capture)"),
    ("branch", "Branch (--branch this Attempt ran against)"),
]


def esc(value):
    return html.escape("" if value is None else str(value))


def fmt(value, default=MISSING):
    if value is None or value == "":
        return esc(default)
    return esc(value)


def badge(word):
    cls = "badge badge-%s" % esc(word).lower().replace(" ", "-")
    return '<span class="%s">%s</span>' % (cls, esc(word))


def latest_attempt(surface):
    attempts = surface.get("attempts") or []
    return attempts[-1] if attempts else None


STYLE = """
<style>
  :root { color-scheme: light; }
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; margin: 0; padding: 24px;
         background: #f7f7f8; color: #1a1a1a; }
  a { color: #2454b0; }
  h1 { margin-top: 0; }
  .meta { color: #666; font-size: 0.9em; margin-bottom: 20px; }
  .pair, .surface, .attempt { background: #fff; border: 1px solid #ddd; border-radius: 8px;
    padding: 16px; margin-bottom: 16px; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.92em;
    vertical-align: top; }
  th { background: #f0f0f2; }
  tr.row-fail td { background: #fdeceb; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.82em;
    font-weight: 600; color: #fff; }
  .badge-passed { background: #1f8a4c; }
  .badge-failed { background: #c0392b; }
  .badge-halted { background: #c0392b; }
  .badge-blocked, .badge-not_applicable, .badge-not_implemented, .badge-pending,
  .badge-stale { background: #8a8f98; }
  .badge-in_progress { background: #b8860b; }
  .badge-pass { background: #1f8a4c; }
  .badge-fail { background: #c0392b; }
  .badge-not-captured { background: #8a8f98; }
  .badge-attention { background: #c0392b; }
  .badge-incomplete { background: #8a8f98; }
  .badge-trusted-render { background: #1f8a4c; }
  .badge-check-render { background: #b8860b; }
  .badge-unknown-render { background: #8a8f98; }
  .badge-mechanical { background: #b8860b; }
  .badge-assertion { background: #c0392b; }
  .badge-environment { background: #6b2fa0; }
  details > summary { cursor: pointer; font-weight: 600; margin: 8px 0; }
  iframe.cma-render { width: 100%; height: 900px; border: 1px solid #ccc; border-radius: 4px; }
  pre { background: #f4f4f5; border: 1px solid #ddd; border-radius: 4px; padding: 10px;
    overflow-x: auto; font-size: 0.85em; }
  img.evidence-shot { max-width: 100%; border: 1px solid #ccc; border-radius: 4px; }
  .surface-header { display: flex; align-items: center; gap: 10px; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chips a { text-decoration: none; }
</style>
"""


# --- provenance / evidence -----------------------------------------------------------------

def render_provenance(provenance, surface_name, code):
    rows = []
    for key, label in PROVENANCE_FIELD_LABELS:
        # .get(), not [] - "branch" was added to the canonical envelope after 28 codes' worth
        # of Attempts already existed (data/manifest.json, 2026-09-10). Every Attempt recorded
        # by the current run_validation.py always carries it (None or a real value, same as
        # every other field); a missing key means only "recorded before this field existed",
        # never a producer regressing the shape, so it degrades to fmt()'s own NOT CAPTURED
        # rather than raising - a legitimate one-time schema addition, not shape tolerance.
        value = provenance.get(key)
        if key in ("capture", "control") and value:
            value = os.path.basename(value)
        rows.append("<tr><th>%s</th><td>%s</td></tr>" % (esc(label), fmt(value)))
    return "<table>%s</table>" % "".join(rows)


def locate_cma_evidence(code, attempt):
    """The exact render THIS Attempt produced - via handles.cma_log_id, never the newest file in
    evidence/run-<code>/. Returns {"html": path|None, "provenance_json": path|None, "reason":
    str|None}."""
    log_id = (attempt.get("handles") or {}).get("cma_log_id")
    if log_id is None:
        return {"html": None, "provenance_json": None,
                "reason": "no cma_log_id recorded for this Attempt"}
    run_dir = os.path.join(EVIDENCE_ROOT, "run-%s" % code)
    html_path = os.path.join(run_dir, "cma_%s_log%s.html" % (code, log_id))
    prov_path = os.path.join(run_dir, "cma_%s_log%s.provenance.json" % (code, log_id))
    return {
        "html": html_path if os.path.exists(html_path) else None,
        "provenance_json": prov_path if os.path.exists(prov_path) else None,
        "reason": None if os.path.exists(html_path) else "evidence file no longer present",
    }


def locate_schumer_evidence(code, capture_prefix, txt_prefix):
    """Neither Schumer capture is versioned by log id - one live file per code's evidence/
    directory (apply_harness.py's capture_surface overwrites in place on a re-run), so only ever
    meaningful for the LATEST Attempt, never the collapsed history.

    capture_prefix is apply_harness.py's own surface key for the html/png pair
    (`schumer_account_opening` for schumer_box_apply, `schumer_landing` for schumer_box_landing
    - the surface's manifest name and its capture filename differ for the apply one, for
    historical reasons). txt_prefix is the assertion output file's own name, which is the
    manifest surface name for both."""
    run_dir = os.path.join(EVIDENCE_ROOT, "run-%s" % code)
    html_path = os.path.join(run_dir, "%s_%s.html" % (capture_prefix, code))
    png_path = os.path.join(run_dir, "%s_%s.png" % (capture_prefix, code))
    txt_path = os.path.join(run_dir, "%s_%s.txt" % (txt_prefix, code))
    return {
        "html": html_path if os.path.exists(html_path) else None,
        "png": png_path if os.path.exists(png_path) else None,
        "txt": txt_path if os.path.exists(txt_path) else None,
    }


def copy_evidence_file(src, dest_dir, dest_name):
    if not src or not os.path.exists(src):
        return None
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(src, os.path.join(dest_dir, dest_name))
    return dest_name


# --- assertions / attempt rendering --------------------------------------------------------

def render_assertions_table(assertions):
    if not assertions:
        return "<p>%s</p>" % MISSING
    rows = []
    for a in assertions:
        cls = "" if a["passed"] else ' class="row-fail"'
        rows.append(
            "<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                cls, esc(a["label"]), fmt(a["expected"]), fmt(a["actual"]), badge(a["status"])))
    return ("<table><tr><th>Assertion</th><th>Expected</th><th>Actual</th><th>Result</th></tr>"
            "%s</table>" % "".join(rows))


def render_failure(failure):
    if not failure:
        return ""
    rows = ["<tr><th>Class</th><td>%s</td></tr>" % badge(failure["class"]),
            "<tr><th>Step</th><td>%s</td></tr>" % fmt(failure["step"]),
            "<tr><th>Summary</th><td>%s</td></tr>" % fmt(failure["summary"])]
    for key, label in (("expected_vs_observed", "Expected vs. observed"),
                        ("diagnosis", "Diagnosis"), ("finding_ref", "Finding"),
                        ("suggested_action", "Suggested action"), ("resume_from", "Resume from")):
        if failure.get(key) is not None:
            rows.append("<tr><th>%s</th><td>%s</td></tr>" % (esc(label), fmt(failure.get(key))))
    return '<div class="failure"><h4>Failure</h4><table>%s</table></div>' % "".join(rows)


def render_evidence_embed(surface_name, code, attempt, report_code_dir):
    ev_dir = os.path.join(report_code_dir, "evidence")
    parts = []

    if surface_name == "cma":
        located = locate_cma_evidence(code, attempt)
        if located["html"]:
            log_id = attempt["handles"]["cma_log_id"]
            name = "cma_log%s.html" % log_id
            copy_evidence_file(located["html"], ev_dir, name)
            parts.append(
                '<iframe class="cma-render" src="evidence/%s"></iframe>'
                '<p><a href="evidence/%s" target="_blank">Open full agreement in a new tab</a></p>'
                % (name, name))
        else:
            parts.append("<p>%s</p>" % esc(located["reason"] or MISSING))

        # Backbook only: assert_cma_absence.py's own report, proving the launch content is
        # genuinely absent (not just unchecked) against a frontbook control - see
        # run_cma_absence() in run_validation.py.
        absence_txt = os.path.join(EVIDENCE_ROOT, "run-%s" % code, "cma_absence_%s.txt" % code)
        if os.path.exists(absence_txt):
            with open(absence_txt) as fh:
                parts.append("<h4>Absence check (assert_cma_absence.py)</h4><pre>%s</pre>"
                             % esc(fh.read()))

    elif surface_name in ("schumer_box_apply", "schumer_box_landing", "schumer_box_basic"):
        capture_prefix = {
            "schumer_box_apply": "schumer_account_opening",
            "schumer_box_landing": "schumer_landing",
            "schumer_box_basic": "schumer_basic",
        }[surface_name]
        located = locate_schumer_evidence(code, capture_prefix, surface_name)
        if located["png"]:
            png_name = copy_evidence_file(located["png"], ev_dir, "%s.png" % capture_prefix)
            parts.append('<img class="evidence-shot" src="evidence/%s">' % png_name)
        if located["html"]:
            html_name = copy_evidence_file(located["html"], ev_dir, "%s.html" % capture_prefix)
            parts.append('<p><a href="evidence/%s" target="_blank">Open captured HTML</a></p>'
                         % html_name)
        if located["txt"]:
            with open(located["txt"]) as fh:
                parts.append("<pre>%s</pre>" % esc(fh.read()))
        if not any(located.values()):
            parts.append("<p>%s</p>" % MISSING)

    return "\n".join(parts)


def render_attempt_block(surface_name, code, attempt, is_latest, report_code_dir):
    parts = ['<div class="attempt">']
    parts.append('<div class="surface-header">%s <strong>%s</strong> - stage %s</div>' % (
        badge(manifest_mod._derive_status(attempt) or "?"), esc(attempt["attempt_id"]),
        fmt(attempt["stage"])))
    parts.append('<p class="meta">started %s, finished %s</p>' % (
        fmt(attempt.get("started_at")), fmt(attempt.get("finished_at"))))
    parts.append(render_provenance(attempt["provenance"], surface_name, code))

    if surface_name == "cma":
        located = locate_cma_evidence(code, attempt)
        if located["provenance_json"]:
            with open(located["provenance_json"]) as fh:
                raw = json.load(fh)
            preview, allow_unapproved = raw.get("preview"), raw.get("allow_unapproved")
            trusted = preview is True and allow_unapproved is True
            parts.append(
                "<p>%s preview=%s allow_unapproved=%s draft_render=%s</p>" % (
                    badge("trusted-render" if trusted else "check-render"),
                    fmt(preview), fmt(allow_unapproved), fmt(raw.get("draft_render"))))
        else:
            parts.append("<p>%s cma provenance file not found - trust unknown</p>"
                         % badge("unknown-render"))

    if attempt.get("assertions"):
        parts.append(render_assertions_table(attempt["assertions"]))
    if attempt.get("failure"):
        parts.append(render_failure(attempt["failure"]))
    if attempt.get("interventions"):
        parts.append("<h4>Interventions</h4><ul>%s</ul>" % "".join(
            "<li>%s - %s</li>" % (fmt(i.get("at")), fmt(i.get("what")))
            for i in attempt["interventions"]))

    if is_latest:
        parts.append(render_evidence_embed(surface_name, code, attempt, report_code_dir))

    parts.append("</div>")
    return "\n".join(parts)


def render_surface_section(surface_name, code, surface, report_code_dir):
    attempts = surface.get("attempts") or []
    out = ['<div class="surface" id="%s">' % esc(surface_name)]
    out.append("<h3>%s %s</h3>" % (esc(surface_name), badge(surface["status"])))

    if not attempts:
        if surface.get("blocked_on"):
            out.append("<p>Blocked on: %s</p>" % esc(", ".join(surface["blocked_on"])))
        out.append("</div>")
        return "\n".join(out)

    latest = attempts[-1]
    out.append(render_attempt_block(surface_name, code, latest, True, report_code_dir))

    if len(attempts) > 1:
        rows = []
        for a in attempts:
            rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                esc(a["attempt_id"]), fmt(a.get("started_at")), fmt(a["stage"]),
                fmt(a["provenance"].get("template_version"))))
        out.append(
            "<details><summary>Attempt history (%d total)</summary>"
            "<table><tr><th>Attempt</th><th>Started</th><th>Stage</th>"
            "<th>Template version</th></tr>%s</table></details>" % (len(attempts), "".join(rows)))

    out.append("</div>")
    return "\n".join(out)


# --- Pair / root index ----------------------------------------------------------------------

def pair_headline_diff(backbook_expected, frontbook_expected):
    parts = []
    for key, label in EXPECTED_FIELD_LABELS:
        b, f = backbook_expected.get(key), frontbook_expected.get(key)
        if b != f:
            parts.append("%s %s -> %s" % (label, fmt(b), fmt(f)))
    return esc(", ".join(parts)) if parts else "no expected-value differences recorded"


def pair_verdict(pair):
    statuses = []
    for role in ("backbook", "frontbook"):
        run = pair["runs"][role]
        for s in SURFACES:
            statuses.append(run["surfaces"][s]["status"])
    if all(s == "passed" for s in statuses):
        return "pass"
    if any(s in ("failed", "halted") for s in statuses):
        return "attention"
    return "incomplete"


def render_expected_table(expected):
    rows = "".join("<tr><th>%s</th><td>%s</td></tr>" % (esc(label), fmt(expected.get(key)))
                   for key, label in EXPECTED_FIELD_LABELS)
    return "<table>%s</table>" % rows


def render_code_page(run, role, pair):
    code = run["code"]
    report_code_dir = os.path.join(OUTPUT_DIR, "codes", code)
    os.makedirs(report_code_dir, exist_ok=True)

    sections = []
    for s in SURFACES:
        sections.append(render_surface_section(s, code, run["surfaces"][s], report_code_dir))

    body = """<!doctype html><html><head><meta charset="utf-8">
<title>%s - %s</title>%s</head><body>
<p><a href="../../index.html">&larr; back to campaign index</a></p>
<h1>%s <small>(%s)</small></h1>
<p class="meta">Pair %s - ticket %s - reachability %s - strategy uuid %s</p>
<h2>Expected values</h2>
%s
<h2>Surfaces</h2>
%s
</body></html>""" % (
        esc(code), esc(role), STYLE, esc(code), esc(role), esc(pair["pair_id"]),
        esc(pair["ticket"]), esc(run["reachability"]), fmt(run.get("strategy_uuid")),
        render_expected_table(run["expected"]), "\n".join(sections))

    with open(os.path.join(report_code_dir, "index.html"), "w") as fh:
        fh.write(body)


def render_root_index(doc):
    rows = []
    passed_count = sum(1 for p in doc["pairs"] if pair_verdict(p) == "pass")

    for pair in doc["pairs"]:
        verdict = pair_verdict(pair)
        backbook, frontbook = pair["runs"]["backbook"], pair["runs"]["frontbook"]
        diff = pair_headline_diff(backbook["expected"], frontbook["expected"])

        role_rows = []
        for role, run in (("backbook", backbook), ("frontbook", frontbook)):
            cma_latest = latest_attempt(run["surfaces"]["cma"])
            mla_forced = (cma_latest or {}).get("provenance", {}).get("mla_forced")
            chips = " ".join(
                '<a href="codes/%s/index.html#%s">%s</a>' % (
                    run["code"], s, badge(run["surfaces"][s]["status"]))
                for s in SURFACES)
            role_rows.append(
                "<tr><td><a href=\"codes/%s/index.html\">%s</a></td><td>%s</td>"
                "<td>%s</td><td>%s</td><td class=\"chips\">%s</td></tr>" % (
                    run["code"], esc(run["code"]), esc(role), esc(run["reachability"]),
                    fmt(mla_forced), chips))

        rows.append(
            '<div class="pair"><h2>%s %s</h2><p>%s</p><p class="meta">ticket %s</p>'
            '<table><tr><th>Code</th><th>Role</th><th>Reachability</th><th>MLA forced</th>'
            '<th>Surfaces (%s)</th></tr>%s</table></div>' % (
                esc(pair["pair_id"]), badge(verdict), diff, esc(pair["ticket"]),
                ", ".join(SURFACES), "".join(role_rows)))

    body = """<!doctype html><html><head><meta charset="utf-8">
<title>Frontbook fee launch validation</title>%s</head><body>
<h1>Frontbook fee launch validation</h1>
<p class="meta">Generated %s - seeded from %s - database %s / %s - %d of %d Pairs fully PASS
(strict: every one of 10 Surface cells passed)</p>
%s
</body></html>""" % (
        STYLE, esc(datetime.now(timezone.utc).isoformat(timespec="seconds")),
        esc(doc["seeded_from"]), esc(doc["database"].get("compose_project")),
        esc(doc["database"].get("volume")), passed_count, len(doc["pairs"]), "\n".join(rows))

    with open(os.path.join(OUTPUT_DIR, "index.html"), "w") as fh:
        fh.write(body)


def generate(root=_ROOT):
    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    doc = json.loads(open(MANIFEST).read())
    for pair in doc["pairs"]:
        for role in ("backbook", "frontbook"):
            render_code_page(pair["runs"][role], role, pair)
    render_root_index(doc)


def main():
    generate()
    print("Wrote %s" % os.path.join(OUTPUT_DIR, "index.html"))
    print("Open: file://%s" % os.path.join(OUTPUT_DIR, "index.html"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
