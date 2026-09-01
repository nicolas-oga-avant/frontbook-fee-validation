"""Derive CMA render assertions from the L&C-approved redline (LGL-7960).

The redline is a .docx carrying Word tracked changes, which makes both sides of the
launch machine-readable from one source:

    approved final    = kept text + <w:ins>          -> expected for the NEW codes
    pre-change text   = kept text + <w:del>          -> expected for the OLD codes

That second reading is why this reads the markup rather than a text export: the old
codes' AC 4 ("backbook untouched") asserts against the same document, so both
expectations stay pinned to one approved artifact instead of being retyped.

Do NOT reroute this through a PDF export. pdftotext cannot see strikethrough and
concatenates deleted with inserted words, which is what produced the incorrect
"the two summary variants only look like they disagree" reading in avant-templates#74.

Usage:
    python3 extract_redline_assertions.py [--docx PATH] [--out PATH]
"""

import argparse
import json
import re
import zipfile
import pathlib
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Paths are resolved from the workdir root (this file lives in scripts/), so the script works
# regardless of the directory it is invoked from.
ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_DOCX = str(ROOT / "reference" / "redline-LGL-7960-schumer-box-and-cma.docx")
DEFAULT_OUT = str(ROOT / "data" / "redline-assertions.json")

# The approved doc carries two Schumer Boxes whose foreign-transaction rows disagree:
# the 2026-05-07 edit reads "of each foreign transaction", the 2026-04-08 edit reads
# "of each  transaction" -- no "foreign", double space. Product confirmed 2026-08-28
# that the first governs both, so the second is a typo in the approved document and is
# normalized here rather than asserted verbatim. Remove this once the doc is corrected.
TYPO_NORMALIZATIONS = [
    ("of each  transaction in U.S. dollars.", "of each foreign transaction in U.S. dollars."),
    ("Up to  $", "Up to $"),
]

# The foreign-transaction sites were restructured rather than edited in place, so their
# deleted runs reconstruct to fragments ("remainnon-refundable,", a bare "Up to") rather
# than to renderable backbook text. The redline is a frontbook document and simply does
# not state how these render for an unconfigured strategy, so the old-code expectation
# comes from the template's gating instead: absence is how "no foreign transaction fee"
# is expressed, and the summary row falls back to "None".
OLD_CODE_OVERRIDES = {
    "summary_ftf_row": "None",
    "ftf_disclosure_paragraph": None,  # paragraph must not render at all
}

# Fee amounts are parameterized so one assertion serves every strategy code. The order
# matters: the two-digit late fees would otherwise match inside a longer number.
FEE_PLACEHOLDERS = [
    (r"\$41\b", "${late_fee_subsequent}"),
    (r"\$39\b", "${late_fee_subsequent}"),
    (r"\$30\b", "${late_fee_initial}"),
    (r"\$28\b", "${late_fee_initial}"),
    (r"\b3%", "{foreign_transaction_fee}%"),
]


def paragraph_texts(paragraph):
    """Return (final, original) text for one <w:p>, honouring tracked-change nesting."""
    final, original = [], []

    def walk(node, in_ins, in_del):
        for child in node:
            tag = child.tag
            if tag == W + "ins":
                walk(child, True, in_del)
            elif tag == W + "del":
                walk(child, in_ins, True)
            elif tag == W + "t":
                text = child.text or ""
                final.append(text)
                if not in_ins:
                    original.append(text)
            elif tag == W + "delText":
                original.append(child.text or "")
            else:
                walk(child, in_ins, in_del)

    walk(paragraph, False, False)
    return "".join(final), "".join(original)


def normalize(text):
    for wrong, right in TYPO_NORMALIZATIONS:
        text = text.replace(wrong, right)
    return re.sub(r"\s+", " ", text).strip()


def parameterize(text):
    for pattern, placeholder in FEE_PLACEHOLDERS:
        text = re.sub(pattern, placeholder, text)
    return text


def classify(final):
    lowered = final.lower()
    if lowered.startswith("foreign transaction fee:"):
        return "ftf_disclosure_paragraph"
    if lowered.startswith("foreign transactions:"):
        return "foreign_transactions_paragraph"
    if lowered.startswith("late fee."):
        return "late_fee_paragraph"
    if "transaction in u.s. dollars" in lowered:
        return "summary_ftf_row"
    if lowered.startswith("up to"):
        return "summary_late_fee_ceiling"
    return "unclassified"


# The doc renders the Rate and Fee Summary twice, under these headings, because the
# annual-fee half differs by product. It is ONE template site: agreement_base.liquid has a
# single summary block whose fee rows come from the membership_fees partial, driven by
# initial_annual_fee / cma_periodic_fee_structure. So a summary assertion applies to the run
# whose annual-fee shape matches its box, and the other box's copy of it must NOT be
# asserted against that render.
BOX_HEADINGS = {
    "CARDS WITH INTRODUCTORY ANNUAL FEE RATE AND FEE SUMMARY": "introductory_annual_fee",
    "ALL OTHER RATE AND FEE SUMMARY": "all_other",
}


def paragraph_heading_index(root):
    """Map each <w:p> element to the summary box it falls under, by document order."""
    current = None
    mapping = {}

    def walk(node):
        nonlocal current
        for child in node:
            if child.tag == W + "p":
                stripped = " ".join(paragraph_texts(child)[0].split()).strip()
                if stripped in BOX_HEADINGS:
                    current = BOX_HEADINGS[stripped]
                mapping[id(child)] = current
            walk(child)

    walk(root)
    return mapping


def extract(docx_path):
    with zipfile.ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    boxes = paragraph_heading_index(root)
    assertions = []
    for paragraph in root.iter(W + "p"):
        final, original = paragraph_texts(paragraph)
        if normalize(final) == normalize(original):
            continue
        final, original = normalize(final), normalize(original)
        kind = classify(final)

        if kind in OLD_CODE_OVERRIDES:
            old_expect = OLD_CODE_OVERRIDES[kind]
            old_source = "template gating (not derivable from the redline)"
        else:
            old_expect = parameterize(original) or None
            old_source = "redline pre-change text"

        is_summary = kind.startswith("summary_")
        box = boxes.get(id(paragraph)) if is_summary else None

        assertions.append(
            {
                "id": "%s%s" % (kind, "-" + box if box else ""),
                "kind": kind,
                # Which Rate and Fee Summary box this copy came from. Only assert an entry
                # whose box matches the run's annual-fee shape; None means the site renders
                # once regardless of product.
                "summary_box": box,
                "new_codes_expect": parameterize(final),
                "old_codes_expect": old_expect,
                "old_codes_expect_source": old_source,
                "new_codes_expect_literal": final,
            }
        )
    return assertions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docx", default=DEFAULT_DOCX)
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    assertions = extract(args.docx)
    with open(args.out, "w") as handle:
        json.dump({"source": args.docx, "assertions": assertions}, handle, indent=2)

    print("%d assertions -> %s" % (len(assertions), args.out))
    for item in assertions:
        absent = item["old_codes_expect"] is None
        print("\n[%s]  box=%s" % (item["id"], item["summary_box"] or "-"))
        print("  new: %s" % item["new_codes_expect"][:150])
        print("  old: %s" % ("<paragraph absent>" if absent else item["old_codes_expect"][:150]))


if __name__ == "__main__":
    main()
