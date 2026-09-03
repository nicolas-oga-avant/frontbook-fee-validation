"""Schumer box assertions for one Run, at application time.

The same two amounts the cardmember agreement discloses appear on the Schumer box the
applicant sees before they ever have an account: the penalty-fee ceiling and the foreign
transaction row. This asserts them on a captured Schumer box - avant-basic's
`/schumer_box/<uuid>`, the account-opening one behind `/apply?strategy=<uuid>`, or the
Contentful landing page - all three of which render the same disclosure.

    python3 scripts/assert_schumer_box.py evidence/run-0120/schumer_basic_0120.html \
        --code 0120 --control evidence/run-0122/schumer_basic_0122.html

Sentences come from data/redline-assertions.json, and only from the box whose annual-fee
shape matches the Run: the redline's two Schumer Boxes are two product cases of one site,
not two code paths, so asserting both against one capture is always wrong (FINDINGS #10).

MLA codes have no uuid, so none of the three surfaces exists for them (FINDINGS #8). Their
application-time evidence is `predecisioned_terms` plus the agreement, and this script
refuses an MLA code rather than letting one pass by asserting nothing.

Backbook expectations are absence, so a capture of a page that never rendered would pass
every one of them. Two guards: the box must contain the markers a rendered box always has,
and every absence check must fail on a frontbook control or it is reported NO TEETH.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from redline_text import flatten, load_row, own_amounts, partner_amounts, sentence, \
    summary_box_for

# Text a rendered box always carries, whichever surface it came from and whichever code it
# is for. Absence checks against a page that failed to render pass perfectly, so the box has
# to prove it is a box before any of them counts.
LOADED_MARKERS = ("Annual Fee", "Foreign Transaction")

FTF_LABEL = "Foreign Transaction"
ANNUAL_FEE_LABEL = "Annual Fee"

# How far past the label the row's own value can sit once the box is flattened to one line.
# A table flattens to labels-then-values, so the value is not adjacent to its label and a
# bare `"None" in text` passes on a frontbook box that says None anywhere else.
FTF_VALUE_WINDOW = 160


def _label_windows(text, label=FTF_LABEL, width=FTF_VALUE_WINDOW):
    """The stretches of text a Foreign Transaction row's value could occupy."""
    windows, at = [], text.find(label)
    while at != -1:
        windows.append(text[at:at + width])
        at = text.find(label, at + 1)
    return windows


def checks(text, row):
    """[(label, passed)] for one captured Schumer box."""
    box = summary_box_for(row)
    frontbook = row["role"] == "new"
    own = own_amounts(row)
    front = own if frontbook else partner_amounts(row)

    ceiling = sentence("summary_late_fee_ceiling", "new" if frontbook else "old",
                       summary_box=box, late_fee_subsequent=own["late_fee_subsequent"])
    ftf_row = sentence("summary_ftf_row", "new", summary_box=box, **front)
    ftf_backbook = sentence("summary_ftf_row", "old", summary_box=box)

    # The control. The two launch rows are hardcoded on every surface until their tickets ship,
    # so they fail on a correct capture AND on a capture of the wrong screen. The annual fee is
    # strategy-driven today, so it is what tells those two apart: if it is right, the box read
    # this Run's strategy and the fee rows below are the real disclosure.
    annual = "$%s" % ("%g" % float(row["expected_annual_fee_y1"] or 0))
    rows = [("box rendered (%s)" % ", ".join(LOADED_MARKERS),
             all(marker in text for marker in LOADED_MARKERS)),
            ("CONTROL annual fee row quotes %s" % annual,
             any(annual in w for w in _label_windows(text, ANNUAL_FEE_LABEL))),
            ("penalty fee ceiling %r" % ceiling, ceiling in text)]

    if frontbook:
        rows.append(("foreign transaction row %r" % ftf_row, ftf_row in text))
    else:
        windows = _label_windows(text)
        rows += [
            ("foreign transaction row reads %r" % ftf_backbook,
             any(ftf_backbook in w for w in windows)),
            ("NO %r" % ftf_row, ftf_row not in text),
            ("NO frontbook late fee amounts",
             "$%s" % front["late_fee_initial"] not in text
             and "$%s" % front["late_fee_subsequent"] not in text),
        ]
    return rows


def report(path, row, label):
    rows = checks(flatten(path), row)
    width = max(len(name) for name, _ in rows)
    print("== %s  (%s)" % (label, path))
    for name, passed in rows:
        print("  %s %s" % ("PASS" if passed else "FAIL", name.ljust(width)))
    failed = [name for name, passed in rows if not passed]
    print("  verdict: %s" % ("ALL PASS" if not failed else "%d FAILED" % len(failed)))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("capture", help="captured html for the Run's Schumer box")
    ap.add_argument("--code", required=True, help="pricing strategy code, e.g. 0122")
    ap.add_argument("--control", help="a frontbook capture, required for a backbook Run")
    args = ap.parse_args()

    row = load_row(args.code)
    if not row.get("uuid"):
        raise SystemExit(
            "%s is an MLA variant: it has no strategy uuid, so no Schumer box surface "
            "exists for it. Assert predecisioned_terms and the agreement instead."
            % args.code)

    print("Run %s (%s), summary box %s\n" % (row["code"], row["role"], summary_box_for(row)))
    captured = report(args.capture, row, row["role"])

    if row["role"] == "new":
        failed = [name for name, passed in captured if not passed]
        if failed and not any(name.startswith(("box rendered", "CONTROL")) for name in failed):
            print("\nOnly the launch rows failed, and the control passed: this is the documented "
                  "pending state, not a broken capture (FINDINGS #35). Report it as a result.")
        elif failed:
            print("\nThe control or the box-rendered guard failed. Fix the capture before "
                  "reading anything into the fee rows - a wrong screen fails them too.")
        return 0 if not failed else 1

    if not args.control:
        print("\nNo --control given: the absence checks here are unproven. Capture the "
              "frontbook code %s and pass it." % row["replaces_or_replaced_by"])
        return 1

    # The control runs the BACKBOOK check list, not its own: a check has teeth only if the
    # very same assertion fails on a document that carries the content.
    print()
    control = report(args.control, row,
                     "frontbook CONTROL %s under backbook expectations - failures here are "
                     "the point" % row["replaces_or_replaced_by"])

    # The guards are excluded from the teeth count on purpose. `box rendered` is supposed to pass
    # on both, and the annual fee control is supposed to match on both whenever a Pair shares an
    # annual fee - which most Pairs do, since only the launch rows differ between them.
    print()
    guards = ("box rendered", "CONTROL")
    scored = [(name, b, f) for (name, b), (_, f) in zip(captured, control)
              if not name.startswith(guards)]
    toothless = [name for name, b, f in scored if b == f]
    print("checks that discriminate: %d of %d" % (len(scored) - len(toothless), len(scored)))
    for name in toothless:
        print("  NO TEETH  %s - same result on both captures" % name)
    return 0 if all(p for _, p in captured) and not toothless else 1


if __name__ == "__main__":
    raise SystemExit(main())
