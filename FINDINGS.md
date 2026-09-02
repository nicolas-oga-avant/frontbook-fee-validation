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

> **UPDATE 2026-09-01: superseded in part.** The diagnosis below is correct, but the conclusion
> "cannot be tested" is not. The minimal fix at the bottom of this finding is applied locally as
> `zzz_local_mla_stub.rb`, so all 28 Runs are reachable. See `DESIGN.md` decision 7 for the
> constraints on that patch. The underlying defect in `avant-basic` is still unowned - see `ROADMAP.md`.


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
