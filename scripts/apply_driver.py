"""Deterministic driver for the card-application browser walk.

Not standalone - depends on apply_harness.py's helpers being loaded first (same rule as that
module). Load both, then call run_apply():

    CODE=7M83 PASSWORD='...' cat scripts/apply_harness.py scripts/apply_driver.py | browser-harness

apply_driver.py itself runs run_apply() from CODE/PASSWORD env vars when executed this way
(see the __main__ block) and prints one JSON result between APPLY_RESULT_JSON_START/END
markers - the orchestrator reads that block rather than parsing prose output.

To call it interactively instead of via env vars:

    exec(open("scripts/apply_harness.py").read())
    exec(open("scripts/apply_driver.py").read())
    result = run_apply("7M83", password="...")

What this replaces
-------------------
The manual walk documented in surfaces/cma.md Step 3: same stages, same helpers
(autofill_stage, set_tu_scenario, fix_autofill_phone, fix_autofill_address, tick_consents_dom),
same six silent-failure traps - but every `wait(N)` + look is replaced by
submit_and_confirm()/wait_for_stage()/wait_for_external_redirect() polling for the actual
signal (SPA hash change or real customer_applications traffic), so a stage that is genuinely
blocked raises instead of being reported as passed by an agent who checked too early or too
late. See apply_harness.py's "deterministic driving" section for why polling was necessary at
all: a fixed wait produced a false no-op read during the 2026-09-09 manual walk of 7M83.

What this does NOT change
--------------------------
Nothing about the flow itself, the consent/address/last-name fixups, or which fields get
autofilled - those are exactly what surfaces/cma.md documents and what apply_harness.py's
helpers already did by hand. A UI change to the apply flow (a renamed input, a relabeled
button) breaks this the same way it would break the manual walk, except there is no longer an
LLM in the loop to notice and adapt - it raises with the page's own validation text attached
instead. Treat a SubmitFailed here as a signal to go drive the stage by hand and see what
actually changed, not as a bug in this script to route around.
"""

import json
import os
from urllib.parse import urlparse


def run_apply(code, password, out_root=None, stage_timeout=20, redirect_timeout=25,
              capture_schumer_apply=True):
    """Walk one application to the post-password redirect. Returns (and writes to
    evidence/run-<code>/apply_result.json) the handles a console script needs next:
    application_uuid, plus which code and last name this Run actually used.

    Raises SubmitFailed if any stage does not confirm - see apply_harness.py. Nothing here
    decides pass/fail on fee content (hard rule 2); this only gets an application to the
    point the console steps take over.

    capture_schumer_apply captures the account-opening Schumer box (surfaces/schumer_box_apply.md)
    for a direct code, since it exists only part-way through this exact walk - right after
    landing on #/personal_continued and before that stage's own fields are filled - and is
    otherwise unreachable. Ignored for an MLA-forced code: it has no strategy uuid, so the
    surface does not exist for it (FINDINGS #8).
    """
    plan = apply_plan(code)

    new_incognito_tab()
    new_tab(plan["url"])
    wait_for_load()
    reached = wait_for_stage("personal", timeout=stage_timeout)
    if reached != "personal":
        raise SubmitFailed(
            "never reached #/personal within %ss of navigating - stuck at %r"
            % (stage_timeout, reached))

    stages = {}
    schumer_apply_capture = None

    # #/personal - tu_last_name must be set AFTER autofill, which overwrites the last name.
    autofill_stage()
    set_tu_scenario(plan["tu_last_name"])
    fix_autofill_phone()
    tick_consents_dom()
    stages["personal"] = submit_and_confirm(next_stage="personal_continued", timeout=stage_timeout)

    # The account-opening Schumer box exists only right here: part of #/personal_continued's
    # own markup, before its fields are autofilled. Capture before touching anything else.
    if capture_schumer_apply and not plan["mla_forced"]:
        schumer_apply_capture = capture_surface(
            code, "schumer_account_opening", navigate=False, element="table.schumer-box",
            root=out_root)

    # #/personal_continued - address must be overwritten whole; extra IL consent may appear.
    autofill_stage()
    fix_autofill_address()
    tick_consents_dom()
    stages["personal_continued"] = submit_and_confirm(next_stage="rates_terms", timeout=stage_timeout)

    # #/rates_terms - creditHardPullConsent blocks approval if missed.
    autofill_stage()
    tick_consents_dom()
    stages["rates_terms"] = submit_and_confirm(next_stage="password", timeout=stage_timeout)

    # #/password - submit navigates OFF this origin; no stage() applies after this click.
    set_input("customer.password", password)
    set_input("customer.passwordConfirmation", password)
    drain_events()
    submit_stage()
    final_url = wait_for_external_redirect("staging-app.avant-test.com", timeout=redirect_timeout)

    app_uuid = urlparse(final_url).path.rstrip("/").rsplit("/", 1)[-1]

    result = {
        "code": code,
        "apply_code": plan["apply_code"],
        "mla_forced": plan["mla_forced"],
        "tu_last_name": plan["tu_last_name"],
        "application_uuid": app_uuid,
        "final_url": final_url,
        "stages": stages,
        "schumer_account_opening_capture": schumer_apply_capture,
    }

    out = evidence_dir(code, out_root)
    path = os.path.join(out, "apply_result.json")
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2, default=str)
    result["file"] = path
    return result


# Auto-run only when CODE is actually set, not on __name__ == "__main__": this file is loaded
# via exec(open(...).read()) inside an already-running browser-harness process as often as it
# is piped in standalone, and the former must not auto-run just because __name__ says
# "__main__" there too - CODE being unset is the real signal this is a define-only load.
if os.environ.get("CODE"):
    _password = os.environ.get("PASSWORD") or "Fr0ntbook!Fee2026"
    _result = run_apply(os.environ["CODE"], _password)
    print("APPLY_RESULT_JSON_START")
    print(json.dumps(_result, indent=2, default=str))
    print("APPLY_RESULT_JSON_END")
