"""browser-harness helpers for driving a card application to an approved account.

Executed end to end on 2026-08-31 for strategy 0122. Every workaround here exists because
of a failure actually observed; see RUN-1-WALKTHROUGH.md for the symptom each one fixes.

Not standalone - run it inside browser-harness, which pre-imports js, cdp, click_at_xy,
page_info, goto_url, wait, wait_for_load, switch_tab, press_key:

    cat apply_harness.py driver.py | browser-harness

The single most important rule: **scroll and measure must be separate js() calls.**
scrollIntoView does not take effect within the eval that calls it, so a rect measured in
the same call is the pre-scroll one, and the click lands somewhere harmless with no error.
"""

import json

STRATEGY_UUIDS = {
    # new frontbook codes, from run-matrix.csv
    "0122": "f7ca3250-5403-40f1-9627-8e274349aff7",
    "0123": "991344ab-7889-4333-ae4c-5921b1c30540",
    # old codes, present in both dev and prd Confetti
    "0120": "173b1fb8-525e-488e-9353-63df8b253542",
    "0121": "380c7a04-b4b8-4d65-8218-7c7b133eb213",
}

APPLY_URL = "https://www.dev.avant.com/apply?product_type=credit_card&strategy=%s"
CSP_BASE = "http://localhost:4000/us"


# --- browser context -------------------------------------------------------------------

def new_incognito_tab():
    """One fresh context per pass, so runs cannot share a customer session.

    Incognito has no Okta session, so anything behind SSO (CSP, basic admin) must run in
    the default profile instead - use new_default_tab() for that.
    """
    ctx = cdp("Target.createBrowserContext")["browserContextId"]
    tid = cdp("Target.createTarget", url="about:blank", browserContextId=ctx)["targetId"]
    switch_tab(tid)
    return ctx, tid


def new_default_tab():
    """A tab in the default profile. Never reuse the user's existing tabs - navigating one
    away loses their work."""
    tid = cdp("Target.createTarget", url="about:blank")["targetId"]
    switch_tab(tid)
    return tid


# --- clicking --------------------------------------------------------------------------

def click_sel(sel):
    """Scroll into view, settle, re-measure, click. See the module docstring."""
    if js("(() => { const e=document.querySelector(%s); if(!e) return 'no'; "
          "e.scrollIntoView({block:'center',behavior:'instant'}); return 'yes'; })()"
          % json.dumps(sel)) != "yes":
        return False
    wait(1)
    r = js("(() => { const e=document.querySelector(%s); const q=e.getBoundingClientRect(); "
           "return JSON.stringify({x:q.x+q.width/2, y:q.y+q.height/2}); })()" % json.dumps(sel))
    p = json.loads(r)
    click_at_xy(p["x"], p["y"])
    return True


def click_text(txt, dom=False):
    """Click the element whose exact text is `txt`.

    dom=True uses element.click() instead of a coordinate click. Required for the customer
    dashboard's dev-tools panel, which renders off-canvas (x=2612 in a 2560-wide viewport)
    where no coordinate click can reach it. React handles the synthetic event fine.
    """
    if dom:
        return js("""
        (() => {
          const e=[...document.querySelectorAll('button,a,[role=button]')]
            .find(x => x.innerText.trim() === %s);
          if(!e) return 'not found';
          e.click(); return 'clicked';
        })()
        """ % json.dumps(txt))
    sel_js = """
    (() => {
      const e=[...document.querySelectorAll('button,a,[role=button]')]
        .find(x => x.innerText.trim().toUpperCase() === %s.toUpperCase() && x.offsetParent);
      if(!e) return 'no';
      e.scrollIntoView({block:'center',behavior:'instant'});
      e.setAttribute('data-bh-target','1');
      return 'yes';
    })()
    """ % json.dumps(txt)
    if js(sel_js) != "yes":
        return "not found"
    wait(1)
    ok = click_sel('[data-bh-target="1"]')
    js("""(() => { const e=document.querySelector('[data-bh-target]');
           if(e) e.removeAttribute('data-bh-target'); return ''; })()""")
    return "clicked" if ok else "measure failed"


# --- form handling ---------------------------------------------------------------------

def set_input(name, value):
    """Set a React-controlled input. The native setter plus input/change/blur is what makes
    React pick the value up; assigning .value alone leaves its internal state stale."""
    return js("""
    (() => {
      const el = document.querySelector('input[name="%s"]');
      if (!el) return 'no such input';
      const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      set.call(el, %s);
      ['input','change','blur'].forEach(t => el.dispatchEvent(new Event(t,{bubbles:true})));
      return el.value;
    })()
    """ % (name, json.dumps(value)))


def fix_autofill_phone():
    """AUTOFILL PERSONAL STAGE can emit a phone whose area code starts with 1 (observed:
    113-288-0530), which fails validation. The only symptom is a silent non-submit."""
    return js("""
    (() => {
      const el = document.querySelector('input[name="person.homePhone"]');
      if (!el) return 'n/a';
      if (!/^1/.test(el.value.replace(/\\D/g,''))) return 'phone ok';
      const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      set.call(el, '3125550134');
      ['input','change','blur'].forEach(t => el.dispatchEvent(new Event(t,{bubbles:true})));
      return 'phone corrected';
    })()
    """)


# Fiserv validates the address components against each other and rejects an
# inconsistent one with HTTP 455 on /fs/maintenance/v2/customnewaccount, which surfaces
# as "Could not set up customer" and halts the issue transition. The dev autofill emits
# `123 Main St, Apt 1, Miami, FL 60601` - a Chicago ZIP on a Florida city.
CONSISTENT_ADDRESS = {
    "customerAddress.address1": "123 Main St",
    "customerAddress.address2": "Apt 1",
    "customerAddress.city": "Chicago",
    "customerAddress.zip": "60601",
}
CONSISTENT_STATE = "IL"


# FakeTransunion (see FINDINGS #14) keys its report off the applicant's LAST NAME.
# Only meaningful against a LOCAL basic with the TU mock registered.
TU_LAST_NAMES = {
    "approved": "approved report",
    "declined": "declined report",
    "freeze": "security freeze",
    "initialfcra": "initial FCRA alert",
    "extendedfcra": "extended FCRA alert",
    "nosubjectfoundmessage": "No Subject Found",
    "missing": "no report at all",
}


def set_tu_scenario(last_name="approved"):
    """Overwrite the autofilled last name so the TU mock returns the wanted report.
    Run on #/personal, after AUTOFILL PERSONAL STAGE."""
    if last_name not in TU_LAST_NAMES:
        raise ValueError("unknown TU scenario %r; expected one of %s"
                         % (last_name, sorted(TU_LAST_NAMES)))
    return set_input("person.lastName", last_name)


def fix_autofill_address():
    """Overwrite the autofilled address with a self-consistent one. Must run on
    #/personal_continued, after AUTOFILL PERSONAL_CONTINUED STAGE."""
    out = {k.split(".")[-1]: set_input(k, v) for k, v in CONSISTENT_ADDRESS.items()}
    out["state"] = js("""
    (() => {
      const s = document.querySelector('select[name="customerAddress.state"], select#customerAddress\\\\.state');
      if (!s) return 'no state select';
      const set = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype,'value').set;
      set.call(s, '%s');
      ['input','change','blur'].forEach(t => s.dispatchEvent(new Event(t,{bubbles:true})));
      return s.value;
    })()
    """ % CONSISTENT_STATE)
    return out


def tick_consents():
    """Consent checkboxes are not HTML-`required`, so form.checkValidity() returns true
    while React silently refuses to submit and renders no error. creditHardPullConsent on
    #/rates_terms is the one that blocks approval."""
    names = json.loads(js("""
    JSON.stringify([...document.querySelectorAll('input[type=checkbox]')]
      .filter(c => !c.checked).map(c => c.name || c.id))
    """))
    for n in names:
        click_sel('input[name="%s"]' % n)
        wait(1)
    return names


def surface_validation():
    """Blur every field, then read the copy back. Validation messages only render after a
    field is touched, so a silently blocked form looks identical to a valid one."""
    js("""[...document.querySelectorAll('input')].forEach(i=>{
      i.dispatchEvent(new Event('focus',{bubbles:true}));
      i.dispatchEvent(new Event('blur',{bubbles:true}));});''""")
    wait(2)
    return json.loads(js("""
    (() => {
      const lines = document.body.innerText.split('\\n').map(s=>s.trim()).filter(Boolean);
      return JSON.stringify(lines.filter(l =>
        /requir|invalid|valid |must |please enter/i.test(l) && l.length < 120).slice(0,12));
    })()
    """))


# --- apply flow ------------------------------------------------------------------------

def stage():
    return (page_info()["url"].split("#")[-1] or "").lstrip("/")


def autofill_stage():
    """Dev tools render a per-stage button named AUTOFILL <STAGE> STAGE."""
    if click_text("DEV TOOLS") != "clicked":
        return "no dev tools"
    wait(2)
    hit = click_text("AUTOFILL %s STAGE" % stage().upper())
    wait(3)
    click_text("CLOSE")
    wait(1)
    return hit


def submit_stage():
    """Submit via the form's own submit button."""
    return click_sel("form button[type=submit]")


def submitted_for_real(events):
    """Distinguish a real submit from a no-op. Only ad/tracking traffic firing means the
    form never submitted. A genuine one hits save_field / send_product_details / submit_page."""
    real = []
    for e in events:
        if e.get("method") != "Network.responseReceived":
            continue
        u = e["params"]["response"].get("url", "")
        if "customer_applications" in u:
            real.append((e["params"]["response"].get("status"), u.rsplit("/", 1)[-1]))
    return real


# --- CSP verification ------------------------------------------------------------------

def csp_search(term):
    """CSP's search is behind button.search-trigger; there is no input until it opens."""
    goto_url(CSP_BASE + "/")
    wait_for_load(); wait(10)
    js("""(() => { const b=document.querySelector('button.search-trigger');
           if(b) b.click(); return ''; })()""")
    wait(4)
    js("""
    (() => {
      const i=document.querySelector('#search-input, input[placeholder="Search ..."]');
      if(!i) return 'no input';
      i.focus();
      const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      set.call(i, %s);
      ['input','change','keyup'].forEach(t=>i.dispatchEvent(new Event(t,{bubbles:true})));
      return 'typed';
    })()
    """ % json.dumps(term))
    wait(3)
    press_key("Enter")
    wait_for_load(); wait(10)
    return json.loads(js("""
    JSON.stringify([...document.querySelectorAll('a[href]')]
      .map(a=>a.getAttribute('href'))
      .filter(h=>/credit_card_accounts|customers/.test(h)))
    """))


def csp_product_details(cc_account_uuid):
    """Read the asserted values off Product Details.

    Returns purchase/cash APR and fee structure. Does NOT return the pricing strategy
    identifier - CSP never displays it, so strategy assignment is inferred from the APR
    plus the accepted apply URL.

    Late Fee Structure is absent unless the CRM checkout contains crm#192;
    check with `grep -rn lateFeeStructure src/` before reading its absence as a defect.
    """
    goto_url("%s/credit_card_accounts/%s/product_details" % (CSP_BASE, cc_account_uuid))
    wait_for_load(); wait(15)
    return json.loads(js("""
    (() => {
      const t = document.body.innerText.split('\\n').map(s=>s.trim());
      const grab = label => { const i = t.findIndex(l => l === label); return i < 0 ? null : t[i+1]; };
      return JSON.stringify({
        purchase_apr: grab('PURCHASE APR'),
        cash_apr: grab('CASH APR'),
        fee_structure: grab('FEE STRUCTURE'),
        credit_line: grab('CREDIT LINE'),
        late_fee_structure: grab('LATE FEE STRUCTURE')
      });
    })()
    """))


def cma_pdf_url(cc_account_uuid):
    """The CSP download link. As of 2026-08-31 this HANGS: basic's GraphQL raises and
    CardMemberAgreementProvider dereferences the null `contents`, so the request never
    returns a body. The CMA is not generated at approval time. See RUN-1-WALKTHROUGH.md.
    """
    return "%s/api/cardMemberAgreements/%s/cma.pdf" % (CSP_BASE, cc_account_uuid)
