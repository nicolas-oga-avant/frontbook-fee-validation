"""Shared reading of rendered documents and of the approved redline.

Three assertion scripts need the same two things - a rendered document flattened to
comparable text, and a sentence from `data/redline-assertions.json` with the run's fee
amounts substituted in. They are here so a sentence cannot drift between them: a copy that
disagrees with the redline produces a wrong PASS, not a crash.

Nothing in here knows about a surface. `assert_cma_absence.py`, `assert_value_table.py` and
`assert_schumer_box.py` own their own expectations; this module owns only the text.
"""

import csv
import html
import json
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REDLINE_PATH = os.path.join(_ROOT, "data", "redline-assertions.json")
MATRIX_PATH = os.path.join(_ROOT, "data", "run-matrix.csv")

# The summary box flattens to labels-then-values, so the Foreign Transaction cell cannot be
# asserted on its own. This whole row pins it to None AND proves the cash advance sentence is
# intact, which is what keeps the FX absence check from passing because the box lost content.
SUMMARY_ROW_BACKBOOK = ("Cash Advance Foreign Transaction The greater of $10 or 3% of the "
                        "amount of the cash advance. None")

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


def norm(s):
    for a, b in _PUNCT:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def entries(path=None):
    with open(path or REDLINE_PATH) as fh:
        return json.load(fh)["assertions"]


def redline(kind, summary_box=None, path=None):
    """The redline entry for one assertion kind, optionally pinned to one summary box.

    The redline carries two Schumer Boxes - two product cases of one site, not two code
    paths (FINDINGS #10). Passing summary_box picks the one whose annual-fee shape matches
    the Run; asserting both against a single render is always wrong.
    """
    for entry in entries(path):
        if entry["kind"] != kind:
            continue
        if summary_box is None or entry.get("summary_box") == summary_box:
            return entry
    raise KeyError("%s%s" % (kind, "" if summary_box is None else " in box %s" % summary_box))


def sentence(kind, side, summary_box=None, path=None, **amounts):
    """One expected sentence, amounts substituted. `side` is "new" or "old".

    Returns None where the redline has no expectation for that side - the two foreign
    transaction sites were restructured rather than edited, so their pre-change runs
    reconstruct to fragments and the backbook expectation comes from template gating
    instead (FINDINGS #11).
    """
    raw = redline(kind, summary_box, path)["%s_codes_expect" % side]
    return None if raw is None else norm(raw).format(**amounts)


def load_matrix(path=None):
    with open(path or MATRIX_PATH, newline="") as fh:
        return [row for row in csv.DictReader(fh) if row.get("code")]


def load_row(code, path=None):
    for row in load_matrix(path):
        if row["code"] == code:
            return row
    raise KeyError("no row for code %r in run-matrix.csv" % code)


def summary_box_for(row):
    """Which of the redline's two Schumer Boxes a Run renders.

    The boxes differ only in their annual fee row: one quotes a single figure, the other an
    introductory year-one figure and a different year-two one. So the shape of the Run's own
    annual fee decides it, and a code whose two years agree renders the all-other box.
    """
    y1, y2 = row.get("expected_annual_fee_y1"), row.get("expected_annual_fee_y2")
    same = float(y1 or 0) == float(y2 or 0)
    return "all_other" if same else "introductory_annual_fee"


def own_amounts(row):
    """The fee amounts one Run expects on its own documents, as the redline names them."""
    return dict(late_fee_initial=row["expected_late_fee_1"].lstrip("$"),
                late_fee_subsequent=row["expected_late_fee_2"].lstrip("$"),
                foreign_transaction_fee=row["expected_ftf"].rstrip("%"))


def partner_amounts(row, path=None):
    """The amounts of the code this one replaces, or is replaced by.

    A backbook Run's absence checks are written in frontbook amounts: what must be missing
    is the partner's $30/$41/3%, and a backbook row's own `expected_ftf` is "none", which
    substitutes into a sentence nobody will ever render.
    """
    return own_amounts(load_row(row["replaces_or_replaced_by"], path))
