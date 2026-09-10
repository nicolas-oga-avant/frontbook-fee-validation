"""Zero-tool-call capture of the two application-free Schumer surfaces - reuses ROADMAP 2.1's
CDP port. Both are addressed purely by the code's strategy uuid, no application needed.

Launches its own Chrome (never the user's browser), execs apply_harness.py UNMODIFIED into a
namespace bound to that Chrome exactly as run_apply_standalone.py already does for the apply
walk, then calls capture_surface(code, <surface>).

schumer_box_landing - `run()` (LANDING_BASE, an external host):

    LANDING_BASE=https://dev.avant.com python3 scripts/run_schumer_landing_standalone.py 0122

LANDING_BASE must point at a host that renders Contentful drafts: `dev.avant.com` and
`redesign-preview.dev.global.avant.com` both build against the Preview API and render
unpublished entries; `uat.avant.com` and `www.avant.com` do not (verified 2026-09-10, see
avant/.tickets/CSRV-5846/CSRV-5846-NOTES.md). Defaults to dev.avant.com here since that is what
both that ticket's own testing strategy and this repo's schumer_box_landing.md already name.
Needs real settle time after navigation: `SchumerBox.js` opens with
`if (!useIsHydrated()) return null` - the box is client-rendered only and is absent from the
served HTML on every Schumer page, old or new, so a bare `curl` (or a fetch with no wait) can
never see it. capture_surface's own `settle` (default 8s) already accounts for this.

schumer_box_basic - `run_basic()` (SCHUMER_BASE, defaults to APPLY_BASE - the local stack):

    python3 scripts/run_schumer_landing_standalone.py 0122 --surface schumer_basic

`mp`-only route (FINDINGS #35) - needs the local avant-basic stack running on `mp`
(`bootstrap.sh --branch mp`), not an external host: SCHUMER_BASE defaults to APPLY_BASE
(http://localhost:5001), exactly where that stack binds, so no override is needed once it is
up. A plain server-rendered ERB view, not client-hydrated like the landing page - a much
shorter settle suffices.
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from cdp.client import Browser  # noqa: E402

DEFAULT_LANDING_BASE = "https://dev.avant.com"


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


def _capture(surface, code, headless, port, out_root, settle):
    os.environ.setdefault(
        "RUN_MATRIX", os.path.join(os.path.dirname(_HERE), "data", "run-matrix.csv"))
    ns = {}
    with Browser(port=port, headless=headless) as browser:
        ns.update(_build_namespace(browser))
        path = os.path.join(_HERE, "apply_harness.py")
        with open(path) as fh:
            exec(compile(fh.read(), path, "exec"), ns)
        record = ns["capture_surface"](code, surface, settle=settle, root=out_root)
    return record


def run(code, headless=None, port=None, out_root=None, settle=8, landing_base=None):
    os.environ["LANDING_BASE"] = landing_base or os.environ.get(
        "LANDING_BASE", DEFAULT_LANDING_BASE)
    return _capture("schumer_landing", code, headless, port, out_root, settle)


def run_basic(code, headless=None, port=None, out_root=None, settle=3):
    """SCHUMER_BASE is left alone here (apply_harness.py's own default: APPLY_BASE) - the
    caller is responsible for the mp-branch stack already binding to that host/port, not this
    function pointing at it by env-var override."""
    return _capture("schumer_basic", code, headless, port, out_root, settle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="pricing strategy code, e.g. 0122")
    parser.add_argument("--surface", choices=("schumer_landing", "schumer_basic"),
                        default="schumer_landing")
    parser.add_argument("--headless", action="store_true", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--out-root", default=None)
    parser.add_argument("--landing-base", default=None)
    args = parser.parse_args()

    if args.surface == "schumer_basic":
        record = run_basic(args.code, headless=args.headless, port=args.port,
                           out_root=args.out_root)
    else:
        record = run(args.code, headless=args.headless, port=args.port,
                     out_root=args.out_root, landing_base=args.landing_base)
    print("SCHUMER_CAPTURE_RESULT_JSON_START")
    print(json.dumps(record, indent=2, default=str))
    print("SCHUMER_CAPTURE_RESULT_JSON_END")


if __name__ == "__main__":
    main()
