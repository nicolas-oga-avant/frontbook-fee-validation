"""Backbook absence assertions for a rendered cardmember agreement.

For a backbook code the fee launch content must NOT be there, and "I did not find it" is a
pass only if the check would have found it. So every run asserts twice: once on the backbook
render, and once on a frontbook render as a control. A check that passes on both has no
teeth and is reported as such.

    python3 scripts/assert_cma_absence.py evidence/run-0120/cma_0120_log5.html \
        --control evidence/run-0122/cma_0122_rerender.html --late-fees 28 39

Sentences come from data/redline-assertions.json (the L&C-approved redline), never from a
copy in here. Matching is on whole sentences: the only 3% in a backbook agreement is the
cash advance fee - "the greater of $10 or 3%" - so `'3%' in text` passes for entirely the
wrong reason.

A failure whose cause is this file's own pattern is a Mechanical Failure and is yours to fix.
A failure where the document genuinely disagrees is a RESULT - record it, never "fix" it.
The two look identical in the output, so read the document before touching a pattern.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redline_text import (REDLINE_PATH, SUMMARY_ROW_BACKBOOK as SUMMARY_ROW, flatten,
                          sentence)


def checks(text, late_fee_initial, late_fee_subsequent, ftf, redline_path=None):
    """[(label, passed)] for one rendered document, backbook expectations."""
    late = sentence("late_fee_paragraph", "old", path=redline_path,
                    late_fee_initial=late_fee_initial, late_fee_subsequent=late_fee_subsequent)
    foreign_old = sentence("foreign_transactions_paragraph", "old", path=redline_path)
    ftf_paragraph = sentence("ftf_disclosure_paragraph", "new", path=redline_path,
                             foreign_transaction_fee=ftf)

    return [
        ("late fee paragraph, full sentence, $%s/$%s" % (late_fee_initial, late_fee_subsequent),
         late in text),
        ("foreign transactions paragraph, pre-change wording", foreign_old in text),
        ("summary row: FTF cell None, cash advance sentence intact", SUMMARY_ROW in text),
        ("summary penalty ceiling 'Up to $%s'" % late_fee_subsequent,
         "Up to $%s" % late_fee_subsequent in text),
        ("NO foreign transaction fee disclosure paragraph", ftf_paragraph not in text),
        ("NO 'we will charge a foreign transaction fee of'",
         "we will charge a foreign transaction fee of" not in text),
        ("NO conversion-rate-costs sentence",
         "Any conversion rate costs resulting from" not in text),
        ("NO '%s%% of each foreign transaction'" % ftf,
         "%s%% of each foreign transaction" % ftf not in text),
        ("NO frontbook late fee amounts", "$30" not in text and "$41" not in text),
    ]


def report(path, label, **kw):
    rows = checks(flatten(path), **kw)
    width = max(len(name) for name, _ in rows)
    print("== %s  (%s)" % (label, path))
    for name, passed in rows:
        print("  %s %s" % ("PASS" if passed else "FAIL", name.ljust(width)))
    failed = [name for name, passed in rows if not passed]
    print("  verdict: %s" % ("ALL PASS" if not failed else "%d FAILED" % len(failed)))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("backbook", help="rendered html for the backbook code")
    ap.add_argument("--control", help="rendered html for the frontbook code it replaces")
    ap.add_argument("--late-fees", nargs=2, default=("28", "39"),
                    metavar=("INITIAL", "SUBSEQUENT"))
    ap.add_argument("--ftf", default="3", help="frontbook foreign transaction fee percent")
    ap.add_argument("--redline", default=REDLINE_PATH)
    args = ap.parse_args()

    kw = dict(late_fee_initial=args.late_fees[0], late_fee_subsequent=args.late_fees[1],
              ftf=args.ftf, redline_path=args.redline)
    back = report(args.backbook, "backbook", **kw)
    if not args.control:
        print("\nNo --control given: these passes are unproven. Absence is only an assertion "
              "if the same check fails on a document that has the content.")
        return 0 if all(p for _, p in back) else 1

    print()
    front = report(args.control, "frontbook CONTROL - failures here are the point", **kw)
    print()
    toothless = [name for (name, b), (_, f) in zip(back, front) if b == f]
    print("checks that discriminate: %d of %d" % (len(back) - len(toothless), len(back)))
    for name in toothless:
        print("  NO TEETH  %s - same result on both documents" % name)
    return 0 if all(p for _, p in back) and not toothless else 1


if __name__ == "__main__":
    raise SystemExit(main())
