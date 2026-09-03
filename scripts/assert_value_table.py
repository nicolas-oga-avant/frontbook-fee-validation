"""Layer 1 - the value table for one Run, all five assertion points plus RPF.

Each point catches a different failure, and a Run that only renders the agreement has
tested one of them:

    Confetti              stale or unpromoted config, before a browser walk is wasted
    Decisioned app        what the applicant was quoted at application time
    Agreement inputs      the strategy-to-numbers boundary, no render needed
    Rendered agreement    that those inputs reached the document
    CSP labels            that the agent-facing copy cannot disagree with the document
    RPF                   $25, which comes from Optimizely and never from Confetti

Expected values come from `data/run-matrix.csv` and expected sentences from
`data/redline-assertions.json` - never from a literal in here.

    python3 scripts/assert_value_table.py 0122 \
        --observations evidence/run-0122/observations.json

Confetti is read live unless --offline. Every other point is read from the observations
file that `local-stack/collect_run_observations.rb` writes from inside the stack; a point
with no observation is reported NOT CAPTURED and fails the Run rather than being skipped
quietly, because an uncaptured point looks exactly like a passing one in a summary.

A disagreement here is an Assertion Failure - a result, possibly the defect this campaign
exists to find. Record it. Never adjust an expectation to make a Run go green.
"""

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redline_text import (SUMMARY_ROW_BACKBOOK, flatten, load_row, own_amounts,
                          partner_amounts, sentence, summary_box_for)

CONFETTI_BASE = os.environ.get(
    "CONFETTI_BASE", "https://confetti.boston.k8s.prd.app.avant.com")

PASS, FAIL, MISSING = "PASS", "FAIL", "NOT CAPTURED"
UNVERIFIABLE = "NO ANSWER"


def _percent(value):
    """An APR as a percentage, whether it arrived as 35.99 or as the fraction 0.3599.

    `predecisioned_terms[:apr]` is stored as a fraction and the matrix quotes percent. Anything
    below 1 is a fraction: no card in this campaign is priced under 1% APR.
    """
    apr = _money(value)
    return None if apr is None else (apr * 100 if apr < 1 else apr)


def _money(value):
    """A fee amount as a float, whether it arrived as "$30", "30.00", 30 or None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().lstrip("$").rstrip("%")
    if cleaned.lower() in ("none", "null", "nil", ""):
        return None
    return float(cleaned)


def _check(label, expected, actual, ok=None):
    if actual is None and ok is None:
        return (label, MISSING, expected, actual)
    passed = (expected == actual) if ok is None else ok
    return (label, PASS if passed else FAIL, expected, actual)


# --- point 1: Confetti -------------------------------------------------------------------

def _confetti(path, env):
    url = "%s/config?path=%s&env=%s" % (CONFETTI_BASE, path, env)
    with urllib.request.urlopen(url, timeout=30) as fh:
        return json.load(fh)["config"]


def confetti_point(row, env, offline=False):
    """The config the Run is priced from, read from Confetti itself.

    An MLA code carries no entry of its own: its fees, apr cap and uuid all live on the base
    code, and `cma_pricing_strategy_config` falls back through `code_to_mla` (FINDINGS #8).
    So this point asserts the base code's config for an MLA Run, which is the config that
    actually prices it.
    """
    if offline:
        return [("Confetti not read (--offline)", MISSING, "-", None)]

    code = row["code"]
    base = row.get("mla_base_code") or code
    fees = _confetti("basic.pricing_strategy", env).get(base) or {}
    caps = _confetti("basic.pricing_strategy.apr_caps_by_enabled_timestamp", env)
    param_to_id = _confetti("basic.pricing_strategy.pricing_strategy_param_to_id", env)
    code_to_mla = _confetti("basic.pricing_strategy.pricing_strategy_code_to_mla", env)

    want = own_amounts(row)
    frontbook = row["role"] == "new"
    cap = next((c["apr_cap"] for c in reversed(caps["values"])
                if c["pricing_strategy_id"] == base), None)

    rows = [
        _check("strategy %s has a Confetti entry" % base, True, bool(fees)),
        _check("late_fee_initial", _money(want["late_fee_initial"]) if frontbook else None,
               _money(fees.get("late_fee_initial")),
               ok=(_money(fees.get("late_fee_initial")) == _money(want["late_fee_initial"]))
               if frontbook else fees.get("late_fee_initial") is None),
        _check("late_fee_subsequent",
               _money(want["late_fee_subsequent"]) if frontbook else None,
               _money(fees.get("late_fee_subsequent")),
               ok=(_money(fees.get("late_fee_subsequent"))
                   == _money(want["late_fee_subsequent"])) if frontbook
               else fees.get("late_fee_subsequent") is None),
        _check("foreign_transaction_fee",
               _money(want["foreign_transaction_fee"]) if frontbook else None,
               _money(fees.get("foreign_transaction_fee")),
               ok=(_money(fees.get("foreign_transaction_fee"))
                   == _money(want["foreign_transaction_fee"])) if frontbook
               else fees.get("foreign_transaction_fee") is None),
        _check("apr cap", _money(row["expected_max_apr"]) / 100.0, cap),
    ]

    if row.get("uuid"):
        rows.append(_check("param_to_id resolves the uuid to %s" % code,
                           code, param_to_id.get(row["uuid"])))
    else:
        rows.append(_check("code_to_mla maps %s to %s" % (base, code),
                           code, code_to_mla.get(base)))
    return rows


# --- point 2: the decisioned application -------------------------------------------------

def application_point(row, obs):
    """What the applicant was quoted, read back from the stored applicant data.

    `predecisioned_terms` is the only application-time surface an MLA code has, and it is
    thinner than it looks: it carries no foreign transaction fee at all, and its
    `maximum_late_fee` is the policy constant rather than the strategy's schedule
    (FINDINGS #34). Asserting the launch's fee amounts here would fail on every Run, correct
    template or not, so what is asserted is APR and the annual fees.
    """
    app = obs.get("application") or {}
    terms = app.get("predecisioned_terms") or {}
    if not terms:
        return [("predecisioned_terms", MISSING, "-", None)]

    y2 = _money(row["expected_annual_fee_y2"])
    # The matrix's year-two column is whichever figure the product quotes for year two, and
    # for a monthly-fee strategy (9004: $125 then $10.42/mo) that is the monthly one. Two
    # keys can legitimately carry it, so either satisfies the check and both are reported.
    y2_actual = (_money(terms.get("annual_membership_fee_year_two")),
                 _money(terms.get("monthly_membership_fee_year_two")))

    return [
        _check("decision path strategy", row.get("mla_base_code") or row["code"],
               app.get("decision_path_strategy")),
        _check("apr", _percent(row["expected_max_apr"]), _percent(terms.get("apr"))),
        _check("annual_membership_fee (year one)", _money(row["expected_annual_fee_y1"]),
               _money(terms.get("annual_membership_fee"))),
        _check("year two fee, annual or monthly", y2, y2_actual, ok=y2 in y2_actual),
        _check("maximum_late_fee is the policy constant, not the schedule (FINDINGS #34)",
               35.0, _money(terms.get("maximum_late_fee"))),
    ]


# --- point 3: the agreement inputs -------------------------------------------------------

def agreement_inputs_point(row, obs):
    """`cma_fee_terms` - the three integers the template is handed."""
    terms = (obs.get("agreement_inputs") or {}).get("cma_fee_terms")
    if terms is None:
        return [("cma_fee_terms", MISSING, "-", None)]

    frontbook = row["role"] == "new"
    want = own_amounts(row) if frontbook else dict(late_fee_initial="28",
                                                   late_fee_subsequent="39",
                                                   foreign_transaction_fee=None)
    ftf_expected = _money(want["foreign_transaction_fee"]) if frontbook else None
    return [
        _check("cma_pricing_strategy_identifier", row["code"],
               (obs.get("agreement_inputs") or {}).get("cma_pricing_strategy_identifier")),
        _check("late_fee_initial", _money(want["late_fee_initial"]),
               _money(terms.get("late_fee_initial"))),
        _check("late_fee_subsequent", _money(want["late_fee_subsequent"]),
               _money(terms.get("late_fee_subsequent"))),
        _check("foreign_transaction_fee", ftf_expected,
               _money(terms.get("foreign_transaction_fee")),
               ok=_money(terms.get("foreign_transaction_fee")) == ftf_expected),
    ]


# --- point 4: the rendered agreement -----------------------------------------------------

def rendered_point(row, path):
    """The five template sites, as whole sentences from the redline.

    A backbook Run asserts the three sites the redline states pre-change text for. The two
    that must be absent are not asserted here: absence is only an assertion when the same
    check is run against a frontbook control, which is `assert_cma_absence.py`'s whole job.
    """
    if not path:
        return [("rendered agreement", MISSING, "-", None)]

    text = flatten(path)
    box = summary_box_for(row)
    frontbook = row["role"] == "new"
    side = "new" if frontbook else "old"
    amounts = own_amounts(row) if frontbook else partner_amounts(row)
    late = own_amounts(row)

    rows = [
        _check("late fee paragraph ($%s/$%s)" % (late["late_fee_initial"],
                                                 late["late_fee_subsequent"]),
               True, sentence("late_fee_paragraph", side,
                              late_fee_initial=late["late_fee_initial"],
                              late_fee_subsequent=late["late_fee_subsequent"]) in text),
        _check("summary late fee ceiling, box %s" % box, True,
               sentence("summary_late_fee_ceiling", side, summary_box=box,
                        late_fee_subsequent=late["late_fee_subsequent"]) in text),
        _check("foreign transactions paragraph, %s wording" % side, True,
               sentence("foreign_transactions_paragraph", side, **amounts) in text),
    ]

    if frontbook:
        rows += [
            _check("ftf disclosure paragraph", True,
                   sentence("ftf_disclosure_paragraph", "new", **amounts) in text),
            _check("summary ftf row, box %s" % box, True,
                   sentence("summary_ftf_row", "new", summary_box=box, **amounts) in text),
        ]
    else:
        rows += [
            _check("summary row: ftf cell None, cash advance sentence intact", True,
                   SUMMARY_ROW_BACKBOOK in text),
            ("ftf disclosure absent - proven by assert_cma_absence.py, not here",
             MISSING, "-", None),
        ]
    return rows


# --- point 5: the CSP labels -------------------------------------------------------------

def csp_point(row, obs):
    """The agent-facing copy, which resolves through the same `cma_fee_terms`.

    Asserted so the two cannot disagree: both labels are formatted from the agreement's own
    fee terms, so a label that disagrees with the document means one of them is reading a
    different strategy.
    """
    csp = obs.get("csp")
    if not csp:
        return [("csp labels", MISSING, "-", None)]

    frontbook = row["role"] == "new"
    want = own_amounts(row)
    late_label = "1st: up to $%s | Subsequent: up to $%s" % (
        want["late_fee_initial"] if frontbook else "28",
        want["late_fee_subsequent"] if frontbook else "39")
    ftf_label = ("%s%% of each foreign transaction" % want["foreign_transaction_fee"]
                 if frontbook else None)

    return [
        _check("late_fee_structure", late_label, csp.get("late_fee_structure")),
        _check("foreign_transaction_fee", ftf_label, csp.get("foreign_transaction_fee"),
               ok=csp.get("foreign_transaction_fee") == ftf_label),
    ]


# --- RPF ---------------------------------------------------------------------------------

def rpf_point(row, obs):
    """$25, from Optimizely.

    Memoised per CreditCardAccount and served from a polled datafile, so a long-lived
    console keeps a stale value - the collector stamps `fresh_process` and this refuses to
    call a stale read a pass (FINDINGS #5).
    """
    rpf = obs.get("rpf")
    if not rpf:
        return [("rpf", MISSING, "-", None)]

    # Without an sdk key the flag is served from a datafile committed to the repo, and that
    # snapshot predates the audience this campaign needs. The values it returns are the
    # snapshot's, not the product's, so they are reported as no answer rather than as a
    # product failure - and still fail the Run, because an unanswered point is not a pass.
    if not rpf.get("sdk_key_present"):
        return [("Optimizely answered from a committed datafile snapshot (revision %s), not a "
                 "live pull - RPF is not verifiable on this stack (FINDINGS #36)"
                 % rpf.get("datafile_revision"), UNVERIFIABLE, row["expected_rpf"],
                 rpf.get("initial_fee_amount_cents"))]

    cents = int(_money(row["expected_rpf"]) * 100)
    rows = [
        _check("can_assess_rpf_fees", True, rpf.get("can_assess_rpf_fees")),
        _check("initial_fee_amount_cents", cents, rpf.get("initial_fee_amount_cents")),
        _check("sequential_fee_amount_cents", cents, rpf.get("sequential_fee_amount_cents")),
    ]
    if not rpf.get("fresh_process"):
        rows.append(("read from a fresh process", FAIL, True, rpf.get("fresh_process")))
    return rows


# --- report ------------------------------------------------------------------------------

def render(title, rows):
    print("== %s" % title)
    width = max(len(r[0]) for r in rows)
    for label, status, expected, actual in rows:
        print("  %-11s %s  expected=%r actual=%r" % (status, label.ljust(width),
                                                     expected, actual))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("code", help="pricing strategy code, e.g. 0122")
    ap.add_argument("--observations", help="json written by collect_run_observations.rb")
    ap.add_argument("--rendered", help="rendered agreement html, if not in the observations")
    ap.add_argument("--confetti-env", default="dev")
    ap.add_argument("--offline", action="store_true", help="skip the live Confetti read")
    args = ap.parse_args()

    row = load_row(args.code)
    obs = json.load(open(args.observations)) if args.observations else {}
    if obs.get("code") and obs["code"] != args.code:
        raise SystemExit("observations are for %s, not %s - a Run's evidence is not "
                         "interchangeable" % (obs["code"], args.code))

    rendered = args.rendered or (obs.get("rendered") or {}).get("html")

    print("Run %s (%s, ticket %s), summary box %s\n"
          % (row["code"], row["role"], row["ticket"], summary_box_for(row)))

    points = [
        ("1. Confetti", confetti_point(row, args.confetti_env, args.offline)),
        ("2. Decisioned application", application_point(row, obs)),
        ("3. Agreement inputs", agreement_inputs_point(row, obs)),
        ("4. Rendered agreement", rendered_point(row, rendered)),
        ("5. CSP labels", csp_point(row, obs)),
        ("RPF (orthogonal to the five)", rpf_point(row, obs)),
    ]

    failed, missing = [], []
    for title, rows in points:
        render(title, rows)
        print()
        failed += ["%s / %s" % (title, r[0]) for r in rows if r[1] == FAIL]
        missing += ["%s / %s" % (title, r[0]) for r in rows
                    if r[1] in (MISSING, UNVERIFIABLE)]

    print("verdict: %d failed, %d not captured" % (len(failed), len(missing)))
    for name in failed:
        print("  FAIL         %s" % name)
    for name in missing:
        print("  NOT CAPTURED %s" % name)
    if missing and not failed:
        print("\nAn uncaptured point is not a pass. This Run's value table is incomplete.")
    return 0 if not failed and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
