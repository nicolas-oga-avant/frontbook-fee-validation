"""Zero-tool-call entry point for the apply walk - ROADMAP.md 2.1's CDP port.

Launches its own Chrome (the user's browser is never touched), execs apply_harness.py and
apply_driver.py UNMODIFIED into a namespace bound to that Chrome instead of to browser-harness,
then calls run_apply() exactly as apply_driver.py's own __main__ block does when piped through
browser-harness. Same APPLY_RESULT_JSON_START/END block either way, so a caller parses
identically regardless of which transport ran it.

    python3 scripts/run_apply_standalone.py 0122
    python3 scripts/run_apply_standalone.py 7M83 --password 'Fr0ntbook!Fee2026' --headless

Env vars apply_harness.py itself reads (APPLY_BASE, CSP_BASE, RUN_MATRIX, ...) still apply -
this file only replaces the browser transport, nothing about the flow or its assertions
(hard rule 2: this makes no pass/fail decision, same as apply_driver.py).
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from cdp.client import Browser  # noqa: E402


def _build_namespace(browser):
    return {
        "cdp": browser.cdp,
        "js": browser.js,
        "click_at_xy": browser.click_at_xy,
        "page_info": browser.page_info,
        "goto_url": browser.goto_url,
        "wait": browser.wait,
        "wait_for_load": browser.wait_for_load,
        "switch_tab": browser.switch_tab,
        "press_key": browser.press_key,
        "drain_events": browser.drain_events,
        "new_tab": browser.new_tab,
    }


def run(code, password, headless=None, port=None, out_root=None):
    # apply_driver.py auto-runs its own __main__ block when CODE is set in os.environ (by
    # design - see that file's comment on why it keys off CODE, not __name__). Clear it so
    # exec()-ing that file here never double-runs it against whatever the caller's shell
    # happened to have set.
    os.environ.pop("CODE", None)
    os.environ.pop("PASSWORD", None)
    os.environ.setdefault(
        "RUN_MATRIX", os.path.join(os.path.dirname(_HERE), "data", "run-matrix.csv"))

    ns = {}
    with Browser(port=port, headless=headless) as browser:
        ns.update(_build_namespace(browser))
        for fname in ("apply_harness.py", "apply_driver.py"):
            path = os.path.join(_HERE, fname)
            with open(path) as fh:
                exec(compile(fh.read(), path, "exec"), ns)
        result = ns["run_apply"](code, password, out_root=out_root)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="pricing strategy code, e.g. 0122 or 7M83")
    parser.add_argument("--password", default=os.environ.get("PASSWORD") or "Fr0ntbook!Fee2026")
    parser.add_argument("--headless", action="store_true", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--out-root", default=None)
    args = parser.parse_args()

    result = run(args.code, args.password, headless=args.headless, port=args.port,
                 out_root=args.out_root)
    print("APPLY_RESULT_JSON_START")
    print(json.dumps(result, indent=2, default=str))
    print("APPLY_RESULT_JSON_END")


if __name__ == "__main__":
    main()
