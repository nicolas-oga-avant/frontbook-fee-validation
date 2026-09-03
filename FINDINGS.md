# Findings - frontbook fee launch validation setup

Discovered 2026-08-27. Each entry names the evidence so it can be re-checked rather than trusted.

---

## 1. There are two near-identical pricing sheets, and CSRV-5667 links the wrong one

Same `🐴 Pricing Strategies` title prefix, same three tab names, same two gids
(`557464996`, `375095930`). **Only the title suffix distinguishes them.**

| Doc id | Suffix | Covers |
| --- | --- | --- |
| `14oVWEyuiIVZ02yDEPIyPkgYQOu8Q2eauAAkNlOSmyWk` | Daily Compounding Interest | Jan 2026 wave, $28/$39, no FX. **Linked from CSRV-5667 - wrong for this work.** |
| `14E2VYinXOsuBBu4jRjtlKDlO2FbKAIDdQfvqCoVkNkg` | Late Fee Increase and Foreign Transaction | **Authoritative.** The 14 new codes, $30/$41, 3% FTF, $25 RPF. Linked from parent RFC CSRV-4787. |

Searching the wrong sheet for all 14 codes, `$30`, `$41`, and `/foreign|fx/i` returns zero matches -
a fast way to tell them apart. Snapshot of the right one: `source-sheet-frontbook.csv`.

**Reading either without auth pain:** fetch the CSV export from inside the authenticated page via
browser-harness. A plain `curl` gets 401.

```
js("fetch('https://docs.google.com/spreadsheets/d/<id>/export?format=csv&gid=<gid>',{credentials:'same-origin'})")
```

Use an **absolute** URL - a relative fetch resolves against whatever tab is active. `gviz/tq?sheet=<name>`
silently ignores the sheet name and returns the first tab. Real gids come from `/htmlview`; the tab
DOM elements carry none.

## 2. Confetti is genuinely per-environment, with a release/promotion model

Base `https://confetti.boston.k8s.prd.app.avant.com`. Useful endpoints:

| Endpoint | Use |
| --- | --- |
| `GET /config?path=<key>&env=<env>[&version=N]` | resolved config |
| `GET /config/versions-by-environment` | every key's released version per env, one call |
| `GET /release/history?path=<key>&env=<env>` | per-env release timeline |
| `GET /docs/openapi.json` | full API (Litestar + Scalar) |
| `POST /config`, `POST /release` | create a version, release it to an env |

Envs: `dev`, `uat`, `prd`, `test`, `local`. Unrecognised values return an empty body.

**Two envs returning byte-identical payloads means both are pinned to the same version - it is not
evidence of a shared store.** Dev history for `param_to_id` contains versions 3 and 4 that prd never
received. `basic.pricing_strategy` currently sits at dev:17 / uat:15 / prd:17 / test:15.

Keys avant-basic reads: `basic.pricing_strategy`, `.pricing_strategy_param_to_id`,
`.pricing_strategy_code_to_mla`, `.apr_caps_by_enabled_timestamp`, `.established_model_score_rules`,
`basic.mock_scenarios`, `basic.fraud_model.all_fraud_model_thresholds`.

`PricingStrategies::Service` merges in-repo constants **under** Confetti, so Confetti wins. The
in-repo fallbacks (`lib/confetti/pricing_strategies.rb`, `lib/avant/pricing_strategies/group_*.rb`)
are near-empty - `group_9xxx.rb` is entirely commented out - and are **not** the source of truth.

## 3. MLA variants cannot be tested in dev (12 of the 28 runs)

> **UPDATE 2026-09-01: superseded in part.** The conclusion "cannot be tested" is wrong; all 28
> Runs are reachable. See `DESIGN.md` decision 7 for the constraints on the patch that does it.
>
> **UPDATE 2026-09-02: the diagnosis below is wrong too, for this flow.** The card policy pulls the
> MLA report through the report manager, so `raw_test_data` is never reached and its hardcoded
> `:mla_negative_stub` blocks nothing. The mock that actually serves it defaults every applicant to
> the *positive* fixture. Read **FINDINGS #33** before acting on anything below. The one-line
> `avant-basic` defect described here is real and still unowned, but it is not the blocker.


The 12 MLA codes have no UUID and are never URL-selectable. They are derived at onboarding:

```ruby
# lib/avant/decisioning/channels/onboarding.rb:119
psc = PricingStrategies::Service.pricing_strategy_code_to_mla.fetch(psc, psc) if mla_customer?
```

and `mla_customer?` resolves to a TransUnion MLA report
(`lib/avant/decisioning/interface/card/unsecured/webbank_us.rb:24` ->
`transunion_secondary_summary.military_lending_act_confirmed`).

**In dev this is always false.** `lib/avant/trans_union/gateway.rb` `raw_test_data` hardcodes:

```ruby
when 'transunion_mla'
  :mla_negative_stub          # unconditional - no override
```

The `transunion` branch immediately above it *does* honour a last-name override, which is the
inconsistency.

`test_data/report_manager/transunion/mla/transunion_mla_positive.raw` exists and is **verified
valid** - it contains the `07051` / `01` / `M01` addon triple that
`lib/avant/trans_union/response/response_us.rb#military_lending_act_confirmed?` matches - but nothing
can select it. The two fixtures differ by 2 bytes.

The SSN-keyed alternative (`MAP_FOR_TRANSUNION_MLA_REPORT`, `FakeTransunion::MLA_IDENTIFIERS`) is on
the Report Manager path and is **spec-only**: `config/initializers/mock_services.rb` says "only one
service is included right now" and loads just `avant_card.rb`.

Minimal fix, mirroring the pattern already in that method:

```ruby
when 'transunion_mla'
  force_fake_report == 'mla' ? :mla_positive_stub : :mla_negative_stub
```

One line, no new config, no deploy-time YAML. **No ticket exists for this.** Note it also blocks the
6 *old* MLA runs under AC 4, so it is not resolved by any of the other dependencies.

## 4. For these strategies the APR cap IS the APR, not a ceiling

```ruby
# lib/avant/decisioning/calculations/card/v2.rb:7
def self.calculate_apr(spread, prime_rate, apr_cap = nil)
  apr_cap.nil? ? spread + prime_rate : [spread + prime_rate, apr_cap].min
end
```

Every strategy in Confetti has `spread: 1` (`FIXED_APR_SPREAD` = 100%), a sentinel guaranteeing
`spread + prime_rate` exceeds any plausible cap, so `min` **always** returns the cap. Variable-rate
strategies carry realistic spreads (`0.1074`, `0.1374`, `0.1474`, `0.1774`) where the cap is a true
ceiling. The sheet corroborates: for every fixed row **Base APR == Max APR**.

Consequences:

- Confetti holds **no generic cap entries** - all are strategy-specific - so a missing entry falls
  back to the in-repo `{ apr_cap: 0.2999 }`, consistent across every `webbank_us` product config
  version from v8 to v42. **A missing cap entry ships the card at 29.99% instead of 35.99%,
  silently.** `0123` is the one code where 0.2999 is correct anyway.
- `enabled_at` gates applicability: `enabled_at <= application_created_at`. It is parsed with
  `TZ.chicago.parse` **inside a map over every entry, before any filtering**, so one unparseable
  value raises for every application under every strategy - a platform-wide break, not a
  degradation. `build_confetti_payloads.py` now hard-refuses a non-`YYYY-MM-DD HH:MM` value.
- Backdating is safe here because nothing has ever carried these codes. The dev entries use
  `2026-08-27 00:00` Chicago.

## 5. RPF eligibility is 100% Optimizely, and staging had the wrong amounts

```ruby
# app/models/credit_card_account.rb:191
optimizely_feature :card_rpf_fees,
  additional_context: :current_cardholder_pricing_strategy_identifier

def rpf_fee_eligible?          # :991
  !!rpf_configuration[:can_assess_rpf_fees]
end
```

Confetti's fee values do **not** feed this. Project `17774870816` (Avant Banking), flag
`card_rpf_fees` (`29289190021`, live), audience `29283540142` "RPF/NSF Eligible Card Accounts".

The audience already contains **all 14 new and all 14 old codes** (updated 2026-08-26, likely under
CSRV-5298). Both the staging and production rules reference the *same* audience id, so that edit went
live in **production** immediately - there is no dev-only staging step for audiences.

Two traps:

1. **Staging fee amounts were `3200/4300` while production was `2500/2500`.** Aligned to `2500/2500`
   on 2026-08-27 (variation `29246920108`). If you see $32/$43, you are on a stale datafile.
2. **Rule order.** Staging lists `CSRV-1919 QA` *first*; first match wins. That audience matches one
   hardcoded `product_uuid f95aa5cf-241f-4eb8-a123-cfe81aa17b83` and returns `$1.00/$21.40`. Harmless
   unless you happen to test with that card.

Also: SDKs poll for the datafile, and `@rpf_configuration` is memoised per `CreditCardAccount`
instance - a long-lived console or worker keeps the old value. Use a fresh process.

## 6. `established_model_score_rules` is dead config - do not populate it

Initially assumed required because every old code has an entry and no new code does. Tracing the
consumers shows the chain is broken:

- Only credit configs **V14** and **V15** merge the Confetti values.
- V14/V15 are paired *only* with engines **V29** (non-prescreened) and **V30** (prescreened).
- **V29 defines** `established_v1/v3_max_score_cutoff` **but never calls them** -
  `failing_established_model_v3_decline_score?` uses `stats[:model_decline_score_cutoff]` instead.
  **V30 does not reference them at all.**
- The engines that *do* call them, **V24** and **V26**, are paired with configs V8/V9/V10/V12 - none
  of which merge Confetti.

No policy in the card chain exposes it either, and policy V12 wires Confetti into
`pricing_strategy_id_from_params_map`, `pricing_strategies`, and `apr_caps_by_enabled_timestamp` but
conspicuously not this. The existing entries for old codes are therefore inert too - likely copied
forward by the same pattern-matching.

Confirm in a console if you want certainty (`0120` exists only in Confetti, never hardcoded, so its
presence proves whether a config reads Confetti):

```ruby
%w[V8 V9 V10 V12 V14 V15].each do |v|
  k = "Avant::Decisioning::Config::Credit::Card::Unsecured::WebbankUS::#{v}".constantize
  puts format("%-4s reads Confetti: %s", v, k.established_model_score_rules.key?('0120'))
end
# expect V8/V9/V10/V12 false, V14/V15 true
```

Note the older engines index directly (`stats[...][pricing_strategy_id][:model_score_v1]`), so a
missing key would raise `NoMethodError` rather than decline - but they never see Confetti values.

## 7. Browser-harness / Chrome gotcha that cost real time

Symptom: `CDP WS handshake failed ... remote browser WebSocket connection failed`, while
`--doctor` reports "chrome running". Misleading - it is not a remote-browser problem.

Cause: Chrome's main process pre-binds `127.0.0.1:9222` **without** `--remote-debugging-port` and
serves **HTTP 404** on DevTools paths until the user ticks *"Allow remote debugging for this browser
instance"* at `chrome://inspect/#remote-debugging`. The daemon dials `ws://127.0.0.1:9222` directly
rather than resolving `/json/version`, so the 404 produces a hang, not a clear error.

Diagnose with `curl -s -w '%{http_code}' http://127.0.0.1:9222/json/version` - **404 means the
opt-in has not been granted**; real DevTools returns JSON. The setting is per browser instance and
needs re-granting after a Chrome restart.

A stale `~/.config/browser-harness/inspect-opened` sentinel suppresses the harness's own prompt, so
it fails silently without ever showing the page. Delete it to restore the prompt.

## 8. The 14 codes split 8 / 6 across Confetti keys - not 14 / 14

Easy to misread as an incomplete config. The 14 new codes are **8 base + 6 MLA**, and different keys
need different subsets:

| Key | Needs | Why |
| --- | --- | --- |
| `pricing_strategy_param_to_id` | the **8 base** codes | MLA codes are never URL-selectable |
| `apr_caps_by_enabled_timestamp` | the **8 base** codes | |
| `pricing_strategy_code_to_mla` | **6 entries** (base -> MLA) | `0122` / `0123` have no MLA variant, per the sheet's `MLA: No`; their predecessors `0120` / `0121` have none either |
| `basic.pricing_strategy` | the **8 base** codes | MLA variants carry no definition of their own; fees derive from the base |
| Optimizely RPF audience | **all 14** | it matches on the *account's* strategy identifier, which for an MLA customer is the M code |

A check phrased "how many of the 8 base codes appear in `code_to_mla`" returns `6/8` and looks
broken. It is correct. `code_to_mla` was already complete in dev **and prd** (v6) before this work
started.

It also carries more weight than it looks: `Entity::Account.valid_pricing_strategy_codes` in CCAPI
unions the MLA keypath's `.keys` **and** `.values`, and avant-basic's
`Service.valid_pricing_strategy_codes` adds `code_to_mla.values` - so this key is the only reason the
6 MLA codes are *valid* codes anywhere. Being live in prd causes no exposure, because valid is not
the same as reachable: nothing can select them until `param_to_id` lands.

## 9. Miscellaneous

- **Out of scope:** `7312 / 7M32 / 7412 / 7M42` appear in the sheet with an empty "New Pricing
  Strategies" cell - deliberately staying on $28/$39, not overlooked.
- **CSRV-5298 shipped no `new_fee_structure?` flag**, contrary to its own technical notes. Fee
  amounts live on the pricing strategy in Confetti and `CreditCardAccount#cma_fee_terms` resolves
  them, defaulting to $28/$39/no-FX when unconfigured. So **absence of Confetti config means old fee
  structure** - a positive opt-in, which is why the "strategy NOT in the old list" denylist was not
  implemented as written.
- **The audience carries disabled entries** as `0019#TempRemove`, `3015#TempRemove`,
  `5015#TempRemove` - values suffixed so exact-match never fires.
- **`main` vs `mp`:** the platform-wide `CLAUDE.md` says work from `mp`, but this launch is main-based -
  `dev.avant.com/apply` serves `basic` (main), Ocala blocks mp-based branches, and
  `lib/avant/pricing_strategies/service.rb` exists on `main` but not `mp`. Read `main` for this work.
  **Superseded in part:** whether the launch ships before, after or alongside MP is still open, so
  the harness takes the trunk as a parameter - `bootstrap.sh --branch mp`, ROADMAP 1.8. `main` is
  still the default and still what has actually been walked; what changed is that `mp` is no longer
  unreachable, and that the missing `service.rb` on `mp` is now a thing to expect rather than a
  reason not to try.

## 10. The approved redline disagrees with itself on the foreign transaction row

`redline-LGL-7960-schumer-box-and-cma.docx` (LGL-7960, Approved) carries **two Schumer Boxes**, and
their foreign-transaction rows were inserted with different wording:

| Row | Inserted text | Author / date | Highlight |
| --- | --- | --- | --- |
| A | `3% of each foreign transaction in U.S. dollars.` | Niharika Menon, 2026-05-07 | yellow |
| B | `3% of each  transaction in U.S. dollars.` | Niharika Menon, 2026-04-08 | none |

Row B drops the word **foreign** and leaves a double space. The late fee ceiling rows differ the same
way: `Up to $41` versus `Up to  $41`. Both rows sit inside `<w:ins>` in `word/document.xml`, so both
survive into the approved final. Confirmed at run level, not inferred from a text dump.

**Product confirmed 2026-08-28 that Row A governs**, so Row B is a typo in the approved document.
`extract_redline_assertions.py` normalizes it (`TYPO_NORMALIZATIONS`) rather than asserting it
verbatim; drop that entry once L&C corrects the doc. avant-templates#74 already implements Row A, so
the shipped template is correct.

Worth knowing: #74's PR description attributes the mismatch to a bad flattened read ("made the two
summary variants look like they disagreed"). That attribution is wrong - the variants genuinely
disagree in the source. The conclusion it reached was right for the wrong reason.

**Not a missed site.** The two boxes are headed `CARDS WITH INTRODUCTORY ANNUAL FEE RATE AND FEE
SUMMARY` and `ALL OTHER RATE AND FEE SUMMARY` - two product cases of the same disclosure, each with
its own annual fee row (`$99.96 to $125.04 annually; billed monthly` vs `From $0 to $75`).
`agreement_base.liquid` has a single summary block whose fee rows come from the `membership_fees`
partial, driven by `initial_annual_fee` / `cma_periodic_fee_structure`, and the foreign transaction
row sits outside that partial. One site, rendered twice in the doc.

So the two boxes are two **test cases**, not two code paths, and the matrix already covers both:
`3303` / `3M33` (y1 $0, y2 $39) and `9004` / `9M04` (y1 $125, y2 $10.42 monthly) render the
introductory box; `0122` / `0123` / `3220` / `5217` / `7213` render the all-other box.
`extract_redline_assertions.py` tags each summary assertion with `summary_box` for this reason -
assert only the entry whose box matches the run's annual-fee shape, never both against one render.

## 11. The redline yields the backbook expectation too, except where it doesn't

Tracked changes give both sides from one approved artifact:

```
approved final  = kept + <w:ins>   -> expected for the NEW codes
pre-change text = kept + <w:del>   -> expected for the OLD codes (AC 4)
```

That works for the late fee paragraph, the two ceiling rows and the Foreign Transactions paragraph.
It **fails for the two foreign-transaction sites**, which were restructured rather than edited in
place: their deleted runs reconstruct to fragments (`remainnon-refundable,`, a bare `Up to`), not to
renderable text. The redline is a frontbook document and does not state how those render for an
unconfigured strategy.

So their old-code expectation comes from the template's gating instead - summary row reads `None`,
disclosure paragraph does not render at all - held in `OLD_CODE_OVERRIDES` and labelled in the output
as `old_codes_expect_source`. Do not "fix" this by trusting the mechanical derivation.

Note the late fee paragraph's new and old expectations are byte-identical once parameterized. That is
correct, not a bug: only the amounts differ, and those come from `run-matrix.csv`.

## 12. CONFIRMED: deployed dev basic reads **prd** Confetti, so no new code is reachable

Settled empirically on 2026-08-31 with a two-UUID probe against `www.dev.avant.com/apply`, run in a
browser (a plain `curl` gets a Cloudflare 403 with a `__cf_bm` bot-management cookie, so this cannot
be probed from the shell):

| Code | In dev Confetti | In prd Confetti | Result |
| --- | --- | --- | --- |
| `0122` (new) | yes, v7 | **no**, v6 | -> `/strategy_param_error` |
| `0120` (old) | yes | yes | -> `/apply/216651178`, flow proceeds |

The old code is the control: it proves the URL shape, the UUID and the flow are all correct, so the
new code's redirect isolates to Confetti visibility. `Avant::Env::Confetti.confetti_env` is
`ENV.fetch('CONFETTI_ENV', 'prd')` (`lib/avant/env.rb:2795`) and nothing outside `.env.development`
sets it - no helm chart, no `.avant` terraform. Dev basic therefore resolves against prd.

**This is a deadlock, not just a blocker.** All 8 new-code runs need the codes visible to dev basic;
dev basic only sees prd; and the prd promotion (CSRV-5823) is deliberately gated on validation
passing. Validation cannot pass until promotion, promotion is not allowed until validation.

The break is setting `CONFETTI_ENV=dev` on the dev basic deployment (Vault
`avant/dev/basic/secrets/CONFETTI_ENV` plus a pod restart) - **not** promoting to prd early, which
would put unvalidated frontbook pricing in front of production traffic. No ticket owns this.

The 8 old base codes are unaffected and remain runnable today.

## 13. The dev tools are a UI button, not a bare POST

Step 3's open question is answered: the apply flow renders a **`DEV TOOLS`** button in-page (seen at
`/apply/216651178#/personal`). No need to hand-POST the `dev_tools` routes.

## 14. Local apply declines every card until the TransUnion mock is wired

Symptom: every local application dies at `personal_continued` -> `declined`, logging
`ExternalData::TransunionCredit Error: missing_transunion_report`. That message is a red
herring - the real error is two layers up:

```
Failed to fetch report transunion ...
  Avant::ReportManager::Gateways::Transunion::FoundErrorCode: Error code in response ERROR_CODE: 999-
```

**`999` is Avant's own invented code**, not TransUnion's. `Gateway#exception_response` says so:
"invented error code (999) that does not come from TransUnion. Means we have a problem calling the
service." And the reason it cannot call the service is by design:

```ruby
# lib/avant/env.rb:1424
def self.transunion_url
  return ENV['TRANSUNION_URL'] if ENV['TRANSUNION_URL']
  return 'https://netaccess.not_real_testing.com' unless Avant::Env.production_env?
end
```

Non-production falls through to a deliberately unresolvable hostname.

**Two separate things were missing locally:**

1. `ENABLE_MOCK_SERVICES=1` lives in `.env.development`, but basic's compose `web` service never
   loads that file, so `Avant::Env.enable_mock_services?` was **false** and *both* mock initializers
   silently skipped. Nothing logs when this happens.
2. `config/initializers/mock_services.rb` registers **only** the `avant_card` mocks, even though
   `spec/support/rails/mock_services/report_manager/transunion.rb` (`FakeTransunion`) already exists
   and is fully built. The initializer's own comment calls itself "a first pass ... We'll expand on
   this if it proves useful."

**Fix** (both untracked, so the shared checkout is untouched):
`config/initializers/zzz_local_transunion_mock.rb` registers `FakeTransunion`, plus
`MOCK_TRANSUNION=1` and `ENABLE_MOCK_SERVICES=1` in `avant-basic/docker-compose.override.yml`.
The `zzz` prefix matters - it must load after `mock_services.rb`, which is what enables WebMock.

**FakeTransunion keys the report off the applicant's LAST NAME**, which is the magic-last-name hook
FINDINGS #3 concluded did not exist. It does - just on the report-manager path, not `data_stubs`:

| Last name | Report |
| --- | --- |
| `approved` | approved (use this for the CSRV-5300 runs) |
| `declined` | declined |
| `freeze` | security freeze |
| `initialfcra` / `extendedfcra` | FCRA alerts |
| `nosubjectfoundmessage` | No Subject Found |
| `missing` | no report at all |

So overwrite the autofilled last name with `approved` after `AUTOFILL PERSONAL STAGE`.

Verified 2026-08-31: with this in place a local application reaches `rates_terms` instead of
`declined`.

**Worth upstreaming.** Adding the TransUnion mock to `mock_services.rb` would make local card
applications work out of the box for everyone; today the tree carries the mock but never loads it.

## 15. Bypassing "Onboarding incomplete!" locally via `final_account`

`refresh_credit_card_cache_data_if_needed!` raises until
`onboarding_request_has_been_processed_by_fdr?`, which is just
`!!account["current_credit_line_change_date"]` - a Fiserv-populated field CCAPI has not synced.

**No monkeypatch is needed.** `CreditCardAccount#account` already short-circuits:

```ruby
def account
  return final_account.with_indifferent_access if final_account.present?
```

So writing `final_account` overrides the whole account payload. The `send_cardmember_agreement_at_issuance`
worker even documents this ("the final_account cache supersedes the normal account cache").

**The trap that makes the naive version worthless.** `current_cardholder_pricing_strategy_identifier`
also reads straight off `account[...]` (`credit_card_account.rb:711`). The local CCAPI payload has it
as **nil**, and `AvantApiStubs.card_api_stub(:get_account)` has it as **`"3007"`**. Dropping the stub
in wholesale renders the CMA under strategy 3007, so every fee assertion silently validates the wrong
product. Force it from the application's own decision path tag instead.

```ruby
cca = CreditCardAccount.find(<id>)
tag = DecisionPathTag.where(customer_application_id: cca.customer_application.id,
                            path_key: 'avant_card_initial_strategy')
                     .order(created_at: :desc).first
psi = tag.data['pricing_strategy_id']          # e.g. "0122" - the source of truth
raise 'no pricing strategy' if psi.blank?

real = cca.account.to_h.deep_stringify_keys
stub = AvantApiStubs.card_api_stub(:get_account)[:account].deep_stringify_keys

# stub supplies the Fiserv fields CCAPI lacks; any real value that is present wins
fake = stub.merge(real) { |_k, stub_v, real_v| real_v.nil? ? stub_v : real_v }
fake['current_credit_line_change_date'] = Date.current.to_s
fake['current_cardholder_pricing_strategy_identifier'] = psi

cca.update!(final_account: fake)
cca.invalidate_cached_account!
```

`purchase_daily_rate` and `cash_advance_daily_rate` must be present or
`refresh_credit_card_cache_data_if_needed!` nils `final_account` straight back out. The stub has both.

**Undo:** `cca.update!(final_account: nil)`. Until then the account never reads live data again.

Verified 2026-08-31 on local basic, account 5211958 / strategy `0122`:

| Input | Value |
| --- | --- |
| `pricing_strategy_identifier` | `"0122"` |
| `merchandise_apr` / `cash_advance_apr` | `"35.99"` |
| `cma_apr_cap` | `"35.99"` |
| `initial_annual_fee` / `annual_fee_year_two` | `0` / `0` |
| `cma_periodic_fee_structure` | `"fixed_amf"` |

All match `run-matrix.csv` for `0122`. Note `late_fee_initial` / `foreign_transaction_fee` are absent
because avant-basic#5928 is unmerged - expected, and exactly what that PR adds.

## 16. `rails runner` has no Optimizely client

`OptimizelyInitializer.setup!` is called only from `config/puma.rb`, `130_sidekiq.rb`, and
`Rails.application.console`. A `rails runner` process is none of those, so anything touching a
feature flag dies with:

```
undefined method `optimizely_client' for #<Rails::Application::Configuration>
```

This is **not** an environment problem - a real `rails console` is fine. In a runner script, call
`OptimizelyInitializer.setup!` first.

## 17. Locally-approved applications have no product decision

**Scoped by FINDINGS #27:** true of the dashboard dev-tool approval, not of
`product.approve!`, after which `generate_cardmember_agreement_inputs` succeeds.

`generate_cardmember_agreement_inputs` logs, on every local run:

```
Invalid Data Source! errors={:annual_membership_fee_amount=>["must be a float"]}
Avant::Originations::Data::Sources::DataSourceBuildError: ... Underwriting::ApplyDecisions::Card::Product
```

The message is misleading. Nothing is mistyped: `application_decisions.for_decision_identifier(:product).newest`
is **nil**, so `get_current_decision` calls `missing_dependency!`, `terms` is `{}`, and
`terms[:annual_membership_fee_cents]` is therefore nil. Verified on account 5211958.

The account still carries a real APR (`0.3599`) and credit line (`200000.0`) in its own columns -
those are set at approval - which is why the application looks fully decisioned until something
asks for the decision record itself.

**Impact is confined to `cma_apr_margin_decimal`, which returns nil.** Fee assertions are unaffected
(fees resolve from Confetti), and the margin is expected nil on a fixed-rate strategy. It would show
up as a blank "U.S. Prime Rate Plus Margin of" on a variable-rate render, which matters for the
CSRV-5301 / CSRV-5302 codes.

**Do not fabricate a product decision to silence this.** Inventing terms and then validating fee
content against them defeats the point of the exercise. Either accept the nil margin for fixed-rate
runs, or drive the application through real decisioning rather than the dashboard's
`Approve Product and Skip Ver` dev tool.

## 18. Ocala TemplateFlow is not git-backed, so there is no Template Version to read

**Superseded in part by FINDINGS #21:** the template named below is *not* the one carrying the fee
content. The git-backing observation stands; the render target does not.

Verified 2026-09-01 against `templateflow.ocala.k8s.dev.global.avant.com`, template
`Letter - Cardmember Agreement (CMA) - Key: 1` (`0b480903-330d-42cd-9cb5-7cff942c44f9`), which is
what `credit_card_cardmember_agreement_1` resolves to:

```
git_sha_version: null
source_file:     null
updated_at:      2026-05-20
status:          draft
```

CSRV-4904 extracted the CMA templates to git-backed `.liquid` files and set `source_file` /
`git_sha_version`, and it is merged - but **only in the repo**. Ocala's records predate it and carry
neither field. That sync is CSRV-5219, and it has not run.

Two consequences:

1. **AC 2 cannot pass on Ocala today.** The stored content does not contain `cma_late_fee_initial`,
   `cma_late_fee_subsequent` or `cma_foreign_transaction_fee`, so avant-templates#74's content is not
   there regardless of whether the PR merges.
2. **The Epoch signal defined in `DESIGN.md` decision 5 does not exist on this instance.** Falling
   back to a SHA256 of the template `content` returned by
   `GET /api/v1/templates/<uuid>`, which needs no git-backing. As of 2026-09-01 that is
   `d163a2fe6060b1e2b6363091cf5dcbca89817c3e01da0d8d70e75c74efc112b1` (189,835 bytes).

Prefer `git_sha_version` once CSRV-5219 lands; record both.

## 19. Only one of the three CMA render paths works locally

**Amended by FINDINGS #27:** the middle row's failure depends on how the application was
approved, and the working row needs `template_variables` populated first - the issuance log
has none.

Three entry points exist. Two fail for unrelated reasons, and neither failure mentions the CMA:

| Path | Result |
| --- | --- |
| `product.send_email!(:credit_card_product_overview, ...)` - the issuance path | **422 from TemplateFlow: `Missing Variables: first_name`.** It fails rendering the *email subject* (`send_email.rb:378 subject_from_templateflow`), before the CMA attachment is touched |
| `interface.csp_requested_cardmember_agreement_log` | **`DataSourceBuildError: annual_membership_fee_amount must be a float`.** It calls `generate_cardmember_agreement_inputs`, which needs the product decision a locally-approved application does not have (FINDINGS #17) |
| `CardmemberAgreementLetter.render_pdf(cardmember_agreement_log:, template_name:)` on a log with **stored** `template_variables` | **Works** |

So a re-render must reuse an existing log's `template_variables` rather than regenerate them. Copy
them onto a new `CardmemberAgreementLog` and call `render_pdf` directly.

Note the stored variables from a pre-#5928 run do **not** contain the three `cma_*` fee keys, so such
a render exercises the template's defaults. That is correct for a backbook expectation and is *not*
evidence about frontbook behaviour.

## 20. The baseline render came from an older template than Ocala serves

Re-rendering account 5211958 against Ocala reproduces the baseline's fee content exactly - $28,
$39, no FX paragraph, and the only `3%` is the cash advance sentence - but the documents differ:
41,032 vs 39,589 characters of text. The baseline carries an **Overlimit Fee** row
(`Late Fee Overlimit Fee Up to $39 None`) that Ocala's template does not have at all.

So `evidence/baseline/cma_0122_local.html` was rendered against a *different* TemplateFlow instance
than the one the stack now points at. Compare **fee content**, never bytes, when checking that a
baseline reproduces.

## 21. Template 9658 is the *consolidated* CMA, not `credit_card_cardmember_agreement_1`

Verified 2026-09-02 against production `templateflow.avant.com`.

| Template | UI id | Template ID | Latest version | Carries the new fee content? |
| --- | --- | --- | --- | --- |
| `credit_card_cardmember_agreement_consolidated` | 9658 | `5d5b0b5c-9e69-4bb4-aaa5-68581f7e7c93` | **v7, Draft** (`bd8382f5-fe63-409f-8d58-11104b01def5`) | **Yes** |
| `credit_card_cardmember_agreement_1` | - | `0b480903-330d-42cd-9cb5-7cff942c44f9` | v32, Approved 2026-03-20 | **No** |

The 9658 draft is titled "Cardmember Agreement (CMA) 2026" and its content matches
avant-templates#74 at all five assertion points: `{{ late_fee_initial }}` and
`{{ late_fee_subsequent }}` in the Late Fee paragraph, `{{ late_fee_subsequent }}` in the rate
summary, the `{% if foreign_transaction_fee %}` FX paragraph, the gated summary row that falls back
to `None`, and the gated "conversion rate costs" clause. **No hardcoded `$28` or `$39` remain**, and
no literal `$30`/`$41` were pasted in - the amounts come from the variables, as intended.

`0b480903` has none of the three variables and still hardcodes `$28`/`$39`. Its newest version is an
*approved* v32 from March; there is no pending draft on it.

**This invalidates the render target FINDINGS #18 and the ROADMAP assumed.** A Run only exercises
the content under test if `cardmember_agreement_template_name` resolves to
`:credit_card_cardmember_agreement_consolidated`, which requires `show_consolidated_cma?`
(`app/models/credit_card_account/cardmember_agreement_inputs.rb:27-32`) to be true:

```ruby
return false unless consolidated_cma_enabled?          # optimizely_feature :consolidated_cma
cutoff_date = Avant::Env::CardmemberAgreement.consolidated_cma_cutoff_date
(cutoff_date && issued_at > cutoff_date) ||
  scenario_enabled?(::CreditCardAccount::Scenarios::NEEDS_CONSOLIDATED_CMA)
```

Locally the Optimizely client is stubbed and `CONSOLIDATED_CMA_CUTOFF_DATE` is unset, so the default
path returns false and a Run renders `_1` - hardcoded `$28`/`$39`, no FX paragraph, **for reasons
that have nothing to do with the fee launch**. That is exactly the silent wrong-answer this project
exists to avoid: it looks like a clean backbook pass on a frontbook code.

The `needs_consolidated_cma` scenario is the lever that does not depend on Optimizely. Every Run
must assert the resolved template name, and record the Template ID and Version ID returned by the
render, before trusting any fee assertion.

## 22. `GET /api/v1/templates/<uuid>` returns the APPROVED version, not the draft

Verified 2026-09-02 against production `templateflow.boston.k8s.prd.app.avant.com`.

Fetching the consolidated CMA by uuid returns 96,818 bytes with **no** fee variables and `$28`/`$39`
still hardcoded - while the v7 draft in the UI has 97,403 bytes and all of them. The endpoint is
serving v6, the newest *approved* version.

`DocumentTemplate.latest` (`avant-templates/app/models/document_template.rb:69`) branches on
`allow_unapproved`:

```ruby
if allow_unapproved
  order(created_at: :desc).where("uuid = ... OR template_uuid = ...").first   # newest, draft included
else
  latest_approved_or_exact(uuid, ...)                                          # newest APPROVED
end
```

and `allow_unapproved` is only ever set from the **render** endpoint, where
`app/api/documents.rb:14` requires both flags together:

```ruby
allow_unapproved = params[:preview] && params[:allow_unapproved]
```

The plain template GET takes no such parameter, so it always answers with the approved version.

**The render path is unaffected and picks up the draft correctly.** basic's wrapper defaults both
`preview` and `allow_unapproved` to `!Avant::Env.acts_as_prod?`
(`avant-basic/lib/avant/templateflow/create_document.rb:18-19`), so a local render sends both and
gets v7. ADR 0002 is right.

Two traps follow:

1. **Do not check "has the fee content shipped?" with a template GET.** It reports the approved
   version and would have you conclude the content is missing when the draft under test carries it.
   Read the draft in the UI, or render with `preview` + `allow_unapproved` and assert on the output.
2. **The Epoch fallback in FINDINGS #18 is broken as written.** Hashing the `content` from
   `GET /api/v1/templates/<uuid>` hashes the *approved* version, so the hash does not move when the
   draft is edited - which is the only thing that changes during this campaign. Derive the Epoch
   from the `template_version_uuid` the render returns instead; that is the version actually used.

## 23. `restore.sh` silently failed to exclude patches in a git WORKTREE

Found 2026-09-02 on the first real `bootstrap.sh` run. `restore.sh` reported:

```
avant-basic: 1 tracked-visible override files (expect 0)
```

and carried on. The visible file was `config/initializers/zzz_local_consolidated_cma.rb`, sitting as
`??` in `git status` inside a checkout shared with other agent sessions - one `git add .` from being
committed, which hard rule 4 exists to prevent.

Cause: `restore()` looked for the exclude file at `$repo/.git/info/exclude` behind an `[ -f "$ex" ]`
test. `bootstrap.sh` creates **worktrees**, and in a worktree `.git` is a *file* pointing at the main
clone, so that path does not exist and the test skipped the append without a word:

```
$ ls -ld .git
-rw-r--r--  1 ichigolas  staff  77 .git
$ test -f .git/info/exclude && echo exists || echo MISSING
MISSING
$ git rev-parse --path-format=absolute --git-common-dir
/Users/ichigolas/Source/avant/avant-basic/.git
```

The three older patches looked fine only by luck: the main clone's exclude already listed them from
earlier manual work in `~/Source/avant/avant-basic`, and worktrees share `info/exclude` with the
common dir. Any *new* patch would have been exposed the same way.

Fixed by resolving the path through `git rev-parse --path-format=absolute --git-common-dir`, which is
correct for both a plain clone and a worktree, and by making the verification **exit 1** instead of
printing a mismatch and continuing. Printing "expect 0" next to a 1 and proceeding is the exact
silence-means-failure pattern this project is built to avoid.

## 24. Renaming the compose project does not isolate two stacks - the host ports collide

The compose projects are now named after this workdir rather than a ticket. That gives each stack its
own containers, network and volumes, but **not** its own host ports: `basic` binds 5001, ccapi 7100,
CRM 4000 in the override files, so a second stack dies at

```
Bind for 0.0.0.0:5001 failed: port is already allocated
```

after its db, redis, minio and sidekiq have already started - leaving a half-up stack behind that
needs `down` before a retry.

So only one validation stack runs at a time on a machine, whatever it is called. `bootstrap.sh`'s
pre-flight guard catches the same-project case by inspecting the running container's
`working_dir` label, but not this one, because a differently-named project is invisible to it.

Two useful facts when clearing the way:

- **`docker compose down` keeps named volumes; only `down -v` destroys them.** Volume names are
  keyed to the *project* name, not the working directory, so stopping a stack and bringing it back up
  under the same project name returns the same database - issued accounts, agreement logs and all.
  The old `basic-csrv-5300_ab_postgres16_data` still holds account 5211958 and the 37 agreement logs
  the earlier findings cite.
- The `avant_basic_shared_bundle` volume is declared without `external: true`, so compose warns that
  it "already exists but was created for project csrv-4925". Harmless - the bundle is shared on
  purpose - but it makes every first `up` look like it is doing something wrong.

## 25. `issue!` returns false with no error when `CREDIT_CARD_SHARED_KEY` is unset

The first real local issuance returned `false` from `cca.issue!` - no exception, `errors` empty,
`can_issue?` true. The reason is stored **encrypted** on `card_onboarding_calls`, which is the only
place it appears:

```ruby
CardOnboardingCall.where(customer_application_uuid: "<uuid>").order(:id).last.response
#=> outcome=:error value="value returned (Some({... :shared_key=>nil})) does not meet type
#   constraints: ... shared_key: Constrained<Nominal<String> rule=[type?(String)]>"
```

basic type-constrains its CCAPI client config to Strings, so a nil `CREDIT_CARD_SHARED_KEY`
(`lib/avant/env.rb:1569`) fails the contract **before any HTTP request is made** - which is why
nothing appears in the CCAPI logs and why the failure looks like a silent state-machine refusal.

CCAPI reads the matching value from `AUTHORIZATION_SHARED_KEY` (`credit-card-api/lib/env.rb:191`),
and both were unset. Fixed by setting them to the same value in the two compose overrides. Read the
onboarding call's `response` before investigating anything else when `issue!` returns false.

## 26. The local stack has no customer dashboard, so the runbook's approval step does not exist

After `CREATE PASSWORD` the local apply flow redirects to
`https://avant.staging-app.avant-test.com/verify/<app_uuid>` - `IP_DASH_URL` in avant-basic's
tracked `.env.development`. The dashboard is the separate **customer-dashboard** app, which this
stack does not run, and `http://localhost:5001/verify/<uuid>` is a 404.

So the `dev tools -> Approve Product and Skip Ver` step in the runbook cannot be performed against a
local stack. That button calls `Avant::GraphQL::DevTools::Mutations::ApproveProduct` at
`/customer_dev_tools_graphql`, and **that endpoint is broken on `main`**
(`app/controllers/graph_controller.rb:47-51`):

```ruby
return render status: 404 unless Avant::Env.debug_graphql?
return render status: 404 if variables['customer_id'].blank?   # reads `variables`...
variables = params[:variables]&.to_unsafe_h || {}              # ...assigned only here
```

Ruby treats `variables` as a local from the assignment onward, so the earlier read raises
`NameError: undefined local variable or method 'variables'`. With `debug_graphql?` true the endpoint
500s on every request; with it false it 404s. It cannot work either way. Worth its own defect ticket.

**What to do instead:** approve server-side, which is what the mutation's non-G2 branch does anyway:

```ruby
app = CustomerApplication.find_by!(uuid: "<app_uuid>")
app.product.approve!   # on_g2? == false locally
```

## 27. The issuance agreement log carries no `template_variables`

`cca.issue!` creates a `CardmemberAgreementLog` with `reason_type: "issuance"` and
**`template_variables: nil`**, so `CardmemberAgreementLetter.render_pdf` on it renders nothing.

Two corrections to earlier findings:

- **`generate_cardmember_agreement_inputs` works.** FINDINGS #17 and #19 record it failing with
  `annual_membership_fee_amount must be a float`. That is true of an application approved through the
  dashboard dev tool, which leaves no product decision - **not** of one approved with
  `product.approve!`, which does. After a real approval it returns 30 keys including
  `late_fee_initial`, `late_fee_subsequent` and `foreign_transaction_fee`.
- **Those inputs are not the whole variable set.** Rendering them directly through
  `Avant::Templateflow::CreateDocument` gets a 422:
  `Missing Variables: account_upc2, address_city_state_and_zip, address_full_street,
  card_credit_limit, card_rpf_eligible, card_rpf_maximum_fee_amount, cma_fixed_rate, first_name,
  last_name, ...` - the customer PII, credit limit and RPF flags that the *letter* pipeline merges in.

So the working sequence is: generate the inputs, store them on the log, then render **through
`CardmemberAgreementLetter`**, which supplies the letter data:

```ruby
log.update!(template_variables: cca.generate_cardmember_agreement_inputs)
Avant::ServicingV2::Communications::CardmemberAgreementLetter.render_pdf(
  cardmember_agreement_log: log,
  template_name: :credit_card_cardmember_agreement_consolidated,
)
```

Note `Avant::Templateflow::CreateDocument.call` returns a Verbalize result whose `.value` **raises**
on failure with a message about using `call!`. Use `call!` in a `begin/rescue`, or the real 422 stays
hidden behind a misleading `Verbalize::Failure` error.

## 28. ~~The letter render path does not expose `template_version_uuid`~~ It does

**Wrong as originally written.** Corrected 2026-09-02. It said `CardmemberAgreementLog` has no
column for the version and that the letter path only forwards it to a logger. Both are false on
`main`:

- `cardmember_agreement_logs.template_version_id` is a `uuid` column (`db/structure.sql:5226`).
- `CardmemberAgreementLetter#render_from_templateflow!`
  (`lib/avant/servicing_v2/communications/cardmember_agreement_letter.rb`) writes the response's
  `template_version_uuid` to it on every render, and captures the resolved variable set on a log's
  first render.

The 0122 Run had recorded it all along: agreement log 1 carries
`bd8382f5-fe63-409f-8d58-11104b01def5`. The finding was written from reading `RenderFromTemplate`
alone, whose `should_log?` branch (`!preview && log_reference`) is indeed dead for a preview render -
but that is the `TemplateFlowLog` audit record, not the only place the version lands.

What is true: the *return value* of `render_pdf` is the PDF, so a caller that wants provenance must
read it off the log afterwards, or capture the `CreateDocument` response. `LocalCmaRender` does
both and cross-checks them, so a stale column cannot pass for a fresh render
(`local-stack/zzz_local_cma_render.rb`).

Two things worth knowing that came out of the correction:

- `all_version_uuids` comes back **newest first**: the version in use is its first entry. Template
  9658 had ten as of 2026-09-02.
- `render_pdf` returns the stored document and sends no request when the log already has one, so a
  reused log yields a document whose version id belongs to an earlier render. `LocalCmaRender`
  refuses a log that already holds a document for exactly this reason. One render per log.

## 29. `preview` and `allow_unapproved` are two separate silent failures, not one

Hard rule 3 has always said to assert `preview`. `allow_unapproved` is the more dangerous of the
two and was not being asserted at all.

Both default to `!Avant::Env.acts_as_prod?`
(`lib/avant/templateflow/create_document.rb:18-19`) and neither appears in the render output:

| Flag off | Consequence |
| --- | --- |
| `preview` | drafts stop rendering **and** documents start persisting to production TemplateFlow |
| `allow_unapproved` | TemplateFlow serves the newest *approved* version - v6, with no fee variables and `$28`/`$39` hardcoded (FINDINGS #22) |

The second produces a frontbook Run reporting backbook amounts, with nothing raised and no way to
tell it apart from a real backbook result. `zzz_local_render_provenance.rb` now refuses a
cardmember agreement render unless both are on, before the request is sent.

It is scoped to the three CMA template uuids on purpose: loan contracts pass `preview: false`
legitimately (`app/models/loan_contract.rb:601,715`), and a global raise would break unrelated
flows in the web process with a message about cardmember agreements.

## 30. `grep | grep -q` under `set -o pipefail` fails once the log is big enough

`bootstrap.sh` asserted the `[local]` initializer lines with:

```bash
docker compose exec -T web sh -c 'grep -h "\[local\]" log/development.log' | grep -qF "$want"
```

which passed on 2026-09-02 and died on the same stack an hour later, reporting the initializer had
not run when the line was plainly in the log. The initializers were fine; the check was not.

`grep -q` exits on its first match. The upstream `grep` is then still writing, takes SIGPIPE, and
exits nonzero - and `set -o pipefail` reports the pipeline as failed. On a small log the upstream
grep finishes before the downstream one exits and nothing goes wrong, so the bug only appears once
`log/development.log` is large (21 MB here).

Read the log once into a variable and match with `case` instead. Any `producer | grep -q` in a
`pipefail` script has this bug, including ones that currently pass.

## 31. Coordinate clicks silently do nothing on the apply flow - use `element.click()`

Found on the 0120 walk 2026-09-02, after four wasted iterations on `#/personal`.

`click_text("CONTINUE APPLICATION")` measures the button, dispatches a real CDP mouse event at
its center, and returns `"clicked"`. Nothing happens: the stage does not advance, no validation
copy renders, `form.checkValidity()` is `true`, no element is `aria-invalid`, and the only
network traffic is `check_session_timeout`. `surface_validation()` returns `[]`. It is
indistinguishable from a form that is simply not ready.

`element.click()` on the same button submits immediately - `submit_page` 200 and the stage
advances. The same is true of the consent checkboxes (`tick_consents()` leaves them
`checked: false`) and the dev-tools autofill button.

Cause not fully pinned; the likely candidate is an overlay intercepting at those coordinates
(the page carries a cookie-consent footer and the off-canvas dev-tools panel). What matters is
that the failure is silent on the click side, so the harness now uses `element.click()` for the
apply flow: `submit_stage()`, `tick_consents_dom()`, `autofill_stage()` and `dom_click_text()`.

Two smaller traps in the same area:

- **The submit button's label differs on every stage** - `CONTINUE APPLICATION`,
  `COMPLETE THE APPLICATION AND CONTINUE`, `Send Confirmation Email And Continue`,
  `CREATE PASSWORD`. Select `form.stage button[type=submit]`, never the text.
- **Autofill overwrites the last name**, so `set_tu_scenario("approved")` must run *after*
  autofill or the TransUnion mock returns a report for `Doeeg8` and the application declines.

## 32. `SKILL.md`'s dashboard approval step never worked locally

The runbook's Step 3 table ended with `dashboard /verify/<app_uuid>` ->
`dev tools -> Approve Product and Skip Ver`. FINDINGS #26 had already recorded that this is
impossible on a local stack - the dashboard is the separate customer-dashboard app, which this
stack does not run - but the table was left as it was, so the 0120 walk followed it and hit the
staging redirect again.

After `CREATE PASSWORD` the flow redirects to
`https://avant.staging-app.avant-test.com/verify/<app_uuid>` and the walk is over. Approve
server-side instead, which is what the dev-tools mutation's non-G2 branch does anyway:

```ruby
app = CustomerApplication.find_by!(uuid: "<app_uuid>")
app.product.approve!
```

The lesson is about the docs, not the platform: a corrected finding is not a corrected runbook.
When a finding invalidates a step, edit the step in the same pass.


## 33. Every local applicant is an MLA customer by default, and the fix is not where #3 said

**Symptom.** An application walked under base code `3303` issues under `3M33`, and nothing says so.
Conversely `zzz_local_mla_stub.rb`'s first version patched `TransUnion::Gateway.raw_test_data` per
FINDINGS #3 and made no difference either way: MLA was already positive before it, and still
positive with it.

**Cause.** The card policy answers true to `pull_using_report_manager?(:transunion_mla)`
(`app/models/customer_application/reports.rb:231`), so the MLA pull goes through the report manager
and is served by the WebMock stub, never by `raw_test_data`. The hardcoded `:mla_negative_stub` that
FINDINGS #3 blamed is unreachable on this flow. What the stub does instead is the opposite:

```ruby
# spec/support/rails/mock_services/report_manager/transunion.rb:219
file = MAP_FOR_TRANSUNION_MLA_REPORT.fetch(handler.identifier, :transunion_mla_positive)
```

The map has four SSN entries, one of which is a negative. Every other applicant - every randomly
autofilled one - falls through to the **positive** fixture. Unlike the primary and secondary
reports in the same class, the MLA report consults no last name.

**Verified 2026-09-02** on application 7, last name `approved`, walked for `0120`: the MLA pull
returned `military_lending_act_confirmed = true`.

**Why it matters more than the reverse.** `0122`/`0120`/`0123`/`0121` have no MLA variant, so their
Runs are unaffected and the existing evidence stands. The other 12 URL-reachable codes all do, so
each would silently issue under its M code while the Run believed it was testing the base one - a
plausible wrong answer, not an error.

**Fix.** `zzz_local_mla_stub.rb` prepends `get_mla_report`, dispatching on the applicant's last name
the way the sibling reports already do: a last name containing `mla` gets the positive fixture,
everyone else the negative one. It patches `raw_test_data` the same way so a policy that skips the
report manager cannot diverge silently, but that half is belt and braces - the report-manager path
is the one that fires. `LocalMlaStub.verify!` asserts both halves of the outcome.

Use the last name **`mlaapproved`**, not `mla`: `FakeTransunion` matches the primary report's
`approved` with `include?`, so one name drives both mocks. A plain `mla` applicant is an MLA
customer whose application declines.

The one-line `avant-basic` defect in FINDINGS #3 is still real and still unowned, but it is not what
blocks MLA testing, and fixing it would not have unblocked anything.

## 34. `predecisioned_terms` carries no fee-launch amount at all

**Symptom.** The application-time surface the ticket names for the 12 MLA codes turns out to
disclose neither of the two fees the launch changes. An assertion written from the ticket's wording
- "read `predecisioned_terms` and assert late fees, FX fee, APR, annual fees" - fails on every Run,
frontbook and backbook alike, against a correct template.

**Cause.** The hash is built in `Avant::Decisioning::Interface::Card::Base#predecisioned_terms`
(`lib/avant/decisioning/interface/card/base.rb:22-41`), and its fourteen keys have no foreign
transaction fee. Its one late fee key is not the schedule:

```ruby
# lib/avant/decisioning/interface/card/base.rb:132
def predecisioned_maximum_late_fee
  application.policy.maximum_late_fee     # => 35.0, a constant on every policy version
end
```

`maximum_late_fee` is `35.0` on v1, v4, v5, v6 and v7 alike, and neither subclass under
`interface/card/unsecured/` overrides it. So `predecisioned_terms[:maximum_late_fee]` is `"35.0"`
for a `0122` applicant and `"35.0"` for a `0120` one. Verified on `9b603b8` (main, the trunk under
test), which already contains CSRV-5298.

**What it can still prove.** APR, the annual fees and the minimum credit line, all of which are
strategy-derived, and the fact that the applicant reached a decision under the code the Run is for.
`assert_value_table.py`'s application point asserts exactly those and pins the `35.0` explicitly, so
the gap is recorded on every Run rather than rediscovered.

**Where the fee amounts do reach an application-time surface**: the Schumer box, which is the other
half of the ticket - and see #35 for what that one does with them.

**This is a result, not a workaround** - and it is already owned. CSRV-5841 adds
`late_fee_initial`, `late_fee_subsequent` and `foreign_transaction_fee` to `predecisioned_terms`;
it is In Progress and not on `9b603b8`, which is why the keys are absent here. CSRV-5843 then reads
them in the Schumer box. So the value table asserts the `35.0` as today's truth, and this finding
is the thing to re-check when CSRV-5841 merges - at which point the fee amounts become assertable
on this surface and the expectation here changes.

## 35. Every Schumer box is strategy-blind on both launch rows

**Symptom.** Two things at once, and the first hides the second. On `main` a request to
`/schumer_box/<uuid>` 404s; on `mp` it renders, and renders the pre-change disclosure for a
frontbook code.

**Cause, part one - the route is `mp`-only.** `config/routes.rb` on `origin/mp` (`8030fc5`) has:

```ruby
get "/schumer_box/:pricing_strategy_uuid" => "schumer_box#show", :as => :schumer_box
```

`origin/main` (`121ac52`) has no `schumer` route at all, and no `SchumerBoxController`. So the
ticket naming dev-mp for this surface is not a preference between two environments - it is the only
trunk where the page exists. ROADMAP 1.7 asked not to resolve that by picking one; it resolves
itself. A Run pinned to `main` cannot capture this surface, and should record it as unreachable
rather than as absent content.

**Cause, part two - the two rows are hardcoded.** `app/views/schumer_box/show.html.erb` on `mp`:

```erb
<li><strong>None</strong></li>                                          <!-- Foreign Transaction -->
<li>Up to <strong><%= AppConfig.credit_card_limits.max_late_payment.formatted %></strong></li>
```

`max_late_payment` is `"$39"` in `config/policies/constants/us.yml:239`, the same on both trunks.
`SchumerBoxController#show` builds `@schumer_data` from the strategy's Confetti entry, but it reads
only `spread`, the annual and monthly fees, the apr cap and four display flags - it never reads
`late_fee_initial`, `late_fee_subsequent` or `foreign_transaction_fee`, the three keys CSRV-5298
added.

**So, today, on `mp`:** every strategy's standalone Schumer box says `Up to $39` and
`Foreign Transaction: None`. A frontbook Run fails both assertions; a backbook Run passes them
vacuously, which is why `assert_schumer_box.py` insists on a frontbook control and reports a check
that passes on both as `NO TEETH`.

**Not a harness bug and not to be worked around** (hard rule 2). Either CSRV-5843/5845 wire the new
amounts into this surface, or the launch ships with an application-time disclosure quoting the old
fees. Which one is a question for product, and the evidence for asking it is a capture of this page
for a frontbook uuid.

### Part three - the box customers actually see is on `main`, and does the same thing

The standalone page above is the lesser half. The Schumer box is **also** rendered inside the apply
flow itself, on the `personal_continued` stage (`version_config.yml:618`, the same stage that
returns `predecisioned_terms`), and that one exists on `main` and is what an applicant sees today.

**Walked and captured 2026-09-03** on the local `main` stack, two frontbook strategies:

| Run | Annual Fee row | Foreign Transaction | Late Fee |
| --- | --- | --- | --- |
| `0122` (application 13) | `$0` | **None** | **Up to $39** |
| `9004` (application 14) | `Introductory fee of $125 for the first year. After that, $125.04 and billed monthly at $10.42.` | **None** | **Up to $39** |

The annual fee row proves the box **is** strategy-driven and reads the right strategy - `9004` even
renders the introductory-annual-fee case the redline's second Schumer Box describes. The two launch
rows are hardcoded anyway. Evidence: `evidence/run-0122/schumer_account_opening_0122.{html,png}`
and the same for `9004`.

**Which code renders it.** ~~The `avant_views` gem's HAML partials, so the fix is a gem release
plus a Gemfile bump~~ - **wrong, and worth knowing why.** `avant_views-3.11.2` does carry two
Schumer partials that hardcode exactly these rows
(`.../v2/components/helpers/_schumer_box.html.haml:80,93` and
`v3/.../schumer_box/_credit_card.html.haml:54,70`), and grepping the bundle finds them first. They
are the **legacy Angular renderer** and did not render this page.

The capture settles it: zero `ng-if` attributes (the HAML is full of them), a CSS-modules class
`_schumer-box_3iywt_1`, and the bundle it loaded:

```
https://d1wwep6nkcr60g.cloudfront.net/micro_frontends/11.4.0/assets/main-ZjEofC42.js
```

So it is the **React micro-frontend** - `SchumerBox.tsx` in customer-application-frontend, which is
what CSRV-5843 names. Two dead HAML copies of the same disclosure are still in the gem; that is a
trap for the next person grepping, not the fix site.

**The bundle is pinned by URL**, `react_index_url` in `version_config` (v6.1 -> `11.4.0`), so the
local stack keeps serving the old box until CSRV-5844 bumps that value. It also means the local
stack **can** validate CSRV-5843 before CSRV-5844 lands, by pointing `react_index_url` at the CAF
preview build - the only way to get a pre-deploy assertion out of this surface.

**Tracked, not an open question.** CSRV-5843 (account-opening box, In Progress) and CSRV-5845
(landing pages, In Progress) each own one surface, and both quote the same approved string,
`3% of each foreign transaction in U.S. dollars.` (LGL-7971). So the assertions here are expected
to fail until those ship. Keep them failing and keep them accurate: a fee row that fails is the
pending state, a **box-rendered** guard that fails is a broken capture.

**Capturing it needs a walk, not a URL.** The box is a section of a stage, so it exists only
part-way through an application and has no address of its own. It also sits in a 240px scroll
window over a 740px table, so a plain screenshot clips off the fee rows - exactly the rows in
question. `capture_surface(..., navigate=False, element="table.schumer-box")` handles both.

## 36. Optimizely answers from a datafile committed to the repo, so RPF is unverifiable locally

**Symptom.** A correctly issued `0122` account reads as RPF-ineligible with zero fee amounts:

```json
{"can_assess_rpf_fees": false, "initial_fee_amount_cents": 0, "sequential_fee_amount_cents": 0}
```

No error, no warning. It looks exactly like the product defect the RPF assertion exists to catch.

**Cause.** With no sdk key the client is built from a **snapshot file in the repo**:

```ruby
# config/initializers/129_optimizely.rb:37
unless sdk_key.present? || Avant::Env.production_env?
  return Optimizely::OptimizelyFactory.default_instance(sdk_key, datafile)
end
```

`config/optimizely/datafile.json` is at **revision 1947**, and none of the campaign's 28 codes are
in the `card_rpf_fees` audience it carries - its 43 entries are the pre-2026-08-26 set. Its staging
variation still holds `3200`/`4300`, the stale amounts FINDINGS #5 recorded. So every Run falls
through to the rollout's default rule, which is `false` / `0` / `0` by design.

**What it means for a Run.** RPF cannot be validated on the local stack as configured. The
collector stamps `sdk_key_present` and `datafile_revision`, and `assert_value_table.py` reports the
point as `NO ANSWER` rather than as a failure - while still failing the Run, because an unanswered
point is not a pass. Reporting `$0` as a defect would be a false result; reporting it as a pass
would be worse.

**To actually verify it**, one of two things: set `OPTIMIZELY_SDK_KEY` on the basic container, which
switches the client to the HTTP config manager and a live datafile, or refresh
`config/optimizely/datafile.json` from the project. Both are real changes to a shared checkout, so
neither was done here. The first is the right one - the local snapshot going stale is what produced
this.
