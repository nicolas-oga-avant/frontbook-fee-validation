# Run 1 walkthrough - strategy 0122, corrected mechanics

First end-to-end walk, 2026-08-31. Replaces the guesses in `TEST-STRATEGY.md` steps 2-5.
Everything below is **executed**, not designed.

| | |
| --- | --- |
| Strategy | `0122` (new, frontbook) |
| Strategy UUID | `f7ca3250-5403-40f1-9627-8e274349aff7` |
| Application id | `216651180` |
| Application uuid | `29c8d390-6613-4624-981c-299ba7f578ed` |
| Outcome | **Approved and card issued** (`#/congratulations`) |
| Identity | `Johnbz2 Doeywn`, DOB 01/01/1990, `johnbz2_doeywn_885144613@avant.test` |

## Environment prerequisites

1. **`CONFETTI_ENV=dev` on the Ocala basic deployment.** Without it the new codes are invisible
   and the apply URL bounces to `/strategy_param_error` - see FINDINGS #12.
2. **Chrome remote debugging opt-in** at `chrome://inspect/#remote-debugging`. Note the harness
   connects through its own held CDP connection, so `curl 127.0.0.1:9222/json/version` returning
   **404 is not diagnostic** once the daemon is up - it stayed 404 the whole successful session.
   Trust `browser-harness --doctor` and an actual command instead.
3. **Two browser contexts.** Apply in a fresh incognito context per pass; do admin/CSP work in the
   default profile. Incognito has no Okta session, so it cannot reach anything behind SSO.

```python
ctx = cdp("Target.createBrowserContext")["browserContextId"]
t   = cdp("Target.createTarget", url="about:blank", browserContextId=ctx)["targetId"]
switch_tab(t)
```

## The stage sequence

`/apply?product_type=credit_card&strategy=<UUID>` then:

| Stage | What it needs |
| --- | --- |
| `#/personal` | `AUTOFILL PERSONAL STAGE`, **fix the phone**, tick e-comms consent |
| `#/personal_continued` | `AUTOFILL PERSONAL_CONTINUED STAGE` (fills income, address, rent/own, credit report auth) |
| `#/rates_terms` | `AUTOFILL RATES_TERMS STAGE`, then **tick `creditHardPullConsent`** |
| `#/password` | set both password fields (autofill does not) |
| dashboard `/verify/<app_uuid>/welcome` | dev tools -> **`Approve Product and Skip Ver`** |
| `#/congratulations` | done, account created |

Dev tools are a **UI button per stage**, named `AUTOFILL <STAGE> STAGE`. No need to hand-POST the
`dev_tools` routes for the apply flow.

## Five traps that each cost a cycle

1. **Clicks below the fold silently do nothing.** `CONTINUE APPLICATION` sits at y=1560 in a
   1328-tall viewport; the AX box model returns *page* coordinates, so `click_at_xy` lands off
   screen with no error. Scroll first.

2. **`scrollIntoView` does not apply within the same `js()` eval.** Measuring the rect in the same
   call still returns the pre-scroll position. Split it: scroll, `wait(1)`, then re-measure in a
   second call.

3. **Consent checkboxes are not HTML-`required`.** `form.checkValidity()` returns `true` while React
   refuses to submit, and no error text renders. `creditHardPullConsent` on `#/rates_terms` cost the
   most time here. Enumerate unchecked checkboxes and tick them before every submit.

4. **`AUTOFILL PERSONAL STAGE` can emit an invalid phone number.** It generated `113-288-0530` - an
   area code starting with `1`. The only symptom is a silent non-submit until you blur the fields,
   which surfaces "Please enter a valid 10-digit phone number". Overwrite with a valid area code
   (`3125550134`).

5. **Dashboard dev-tools buttons sit off-canvas.** `Approve Product and Skip Ver` measures at
   x=2612 in a 2560-wide viewport, so no coordinate click can reach it. Use `element.click()` - it
   is a real button with an onClick handler and React handles the synthetic event fine.

To surface a silent validation block, blur every input and re-read the page text:

```python
js("""[...document.querySelectorAll('input')].forEach(i=>{
  i.dispatchEvent(new Event('focus',{bubbles:true}));
  i.dispatchEvent(new Event('blur',{bubbles:true}));});''""")
```

## Test data: do not use a mock case

`AUTOFILL PERSONAL STAGE` generates a fresh randomized identity per run, so runs cannot collide on a
duplicate customer. Use it and let the standard dev TransUnion stub decide.

The `TST_00xx` mock catalogue has **no approved-card case** - every `Card`-labelled case is a decline
or a risk scenario. See `mock-test-cases.md`. `TST_0001` is the fallback if the default stub ever
stops approving.

## Signals that the submit actually worked

Watch for these on `#/rates_terms`; all 200:

```
/api/customer_applications/<id>/save_field
/api/customer_applications/<id>/send_product_details
/api/customer_applications/<id>/submit_page
```

If only `google`/`doubleclick`/`facebook` requests fire, the form never submitted.

## Verified in CSP (local CRM against Ocala basic)

Customer **Johnbz2 Doeywn #416012362**, **Approved Credit Card Account
`128e8549-e663-4d43-82af-d8b08dc08516`**. Product Details shows:

| Field | Value | Expected for `0122` | |
| --- | --- | --- | --- |
| Purchase APR | 35.99% | 35.99% | PASS |
| Cash APR | 35.99% | - | |
| Fee structure | No Annual Fee | $0.00 y1/y2 | PASS |
| Credit line | $200.00 | n/a | |

**The APR is the load-bearing assertion here.** 35.99% rather than 29.99% proves the
`apr_caps_by_enabled_timestamp` entry for `0122` resolved - FINDINGS #4's silent failure mode did not
fire. Combined with the application being accepted at all, the strategy plumbed through end to end.

**No Late Fee Structure field is displayed**, but that is a *branch artifact, not a defect*: this CRM
checkout is on `feat/CSRV-4368-update-crm-to-use-download-url-take-2`, which does not contain
crm#192 (CSRV-4501). `grep -rn "lateFeeStructure" src/` returns nothing. Check it out on a branch
containing crm#192 before treating a missing label as a finding.

CSP does not display the pricing strategy identifier anywhere, so assignment is inferred from the
APR and the accepted apply URL rather than read directly. A direct read needs the admin or a
GraphQL query.

## BLOCKED: the CMA is not retrievable at approval

This answers step 5's biggest unknown - **the CMA is not generated at approval time.**

CSP renders a Cardmember Agreement section with two `PDF` rows, one linking to:

```
/us/api/cardMemberAgreements/<cc_account_uuid>/cma.pdf
```

That request hangs and never returns a body. The CRM container log gives the cause:

```
GraphQL Result Error: ... exception_identifier:6915d75a-fbb5-459b-b304-57e6c736212f
TypeError: Cannot read property 'contents' of null
  at CardMemberAgreementProvider (dist/packages/crm-backend/providers/cardMemberAgreement.js:21:55)
```

So basic's GraphQL raises, CRM gets `null`, and the provider dereferences it unguarded. The rows
render because the list query succeeds; only `contents` is missing.

Ruled out:

- **Not the `mail_me_a_copy` delay.** `cardmember_agreement_workflow_delay` gates
  `Admin::V2::Workflow::Product::CardmemberAgreement#cma_letter_delay`, which is the customer-request
  letter workflow, not generation at account open.
- **Not a slow render.** Two attempts minutes apart, 90s and 180s, both returned nothing.

Next step is the basic-side exception, via `exception_identifier` in Datadog. Two separate questions
to keep apart:

1. What generates CMA contents at account open, and did it run for this account?
2. Independently, `cardMemberAgreement.js:21` dereferences a null without a guard, so a missing
   document becomes a hung request rather than a clean error. That is a CRM defect worth its own
   ticket regardless of how (1) resolves.

## Local CRM setup, corrected

The root `CLAUDE.md` recipe is accurate but misses one step:

**`Dockerfile.dev` never builds the client bundle.** It runs `yarn build` (tsc only); the client comes
from `yarn webpack`. Without it every request 500s with
`Failed to lookup view "login.ejs" in views directory "/app/dist/clientBuild"`, after the server
cheerfully logs `Listening on port 3000`.

```bash
docker compose -p crm-csrv-5300 up -d web
docker compose -p crm-csrv-5300 exec web sh -c 'cd /app && yarn webpack'   # ~53s
# then http://localhost:4000/us/  -> LOGIN WITH AVANT (avantpreview Okta, needs a human)
```

Also: base compose already binds `3000:3000` and compose **appends** ports rather than replacing
them, so the container ends up on both 3000 and 4000. Harmless alone, collides if another project
holds 3000.

**Okta is a human gate.** `avantpreview.oktapreview.com` is a different org from the production Okta,
so there is no session to reuse and an agent cannot complete it. Expect to hand off here once per
session.

## Harness note that cost two cycles

`curl 127.0.0.1:9222/json/version` returned **404 both while connected and while disconnected**. It is
not a usable signal. Use `browser-harness --doctor` (`daemon alive`, `active browser connections`).
The opt-in is per Chrome instance and drops on restart, including a restart triggered by signing in.
