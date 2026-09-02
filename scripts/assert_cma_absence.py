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
import html
import json
import os
import re

REDLINE_REL = os.path.join("data", "redline-assertions.json")

# The summary box flattens to labels-then-values, so the Foreign Transaction cell cannot be
# asserted on its own. This whole row pins it to None AND proves the cash advance sentence is
# intact, which is what keeps the FX absence check from passing because the box lost content.
SUMMARY_ROW = ("Cash Advance Foreign Transaction The greater of $10 or 3% of the amount "
               "of the cash advance. None")

_PUNCT = (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
          ("–", "-"), ("—", "-"), ("\xa0", " "))


def flatten(path):
    """The document as one line of normalized text, tags and entities resolved."""
    raw = open(path, encoding="utf-8").read()
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    for a, b in _PUNCT:
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def _norm(s):
    for a, b in _PUNCT:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _redline(kind, path=None):
    with open(path or REDLINE_REL) as fh:
        for entry in json.load(fh)["assertions"]:
            if entry["kind"] == kind:
                return entry
    raise KeyError(kind)


def checks(text, late_fee_initial, late_fee_subsequent, ftf, redline_path=None):
    """[(label, passed)] for one rendered document, backbook expectations."""
    late = _norm(_redline("late_fee_paragraph", redline_path)["old_codes_expect"]).format(
        late_fee_initial=late_fee_initial, late_fee_subsequent=late_fee_subsequent)
    foreign_old = _norm(
        _redline("foreign_transactions_paragraph", redline_path)["old_codes_expect"])
    ftf_paragraph = _norm(
        _redline("ftf_disclosure_paragraph", redline_path)["new_codes_expect"]).format(
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
    ap.add_argument("--redline", default=REDLINE_REL)
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
