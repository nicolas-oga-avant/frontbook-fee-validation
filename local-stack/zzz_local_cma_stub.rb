# UNTRACKED local-only helper for the frontbook fee launch validation. See FINDINGS #15.
#
# Unblocks CMA generation on a locally-issued card by faking the ONE field Fiserv would have
# filled in overnight. Everything else is real.
#
#   cca.issue!                       # do this FIRST - see below
#   LocalCmaStub.status(cca.id)
#   LocalCmaStub.prepare!(cca.id)
#   LocalCmaStub.revert!(cca.id)
#
# Accepts a CreditCardAccount, its id, or its uuid.
#
# ## Issue the card for real first
#
# An earlier version of this helper also invented a servicing account and forced the pricing
# strategy onto the payload. Both are unnecessary, and the second was dangerous: the canned
# AvantApiStubs account carries pricing strategy "3007", so a wholesale stub renders every CMA
# under the wrong product with nothing failing.
#
# A real `cca.issue!` gives all of that honestly - it runs the onboarding call, creates the
# servicing account, and leaves CCAPI holding the account with its true pricing strategy. It works
# locally provided CCAPI can reach Confetti (it reads CONFETTI_URL, not CONFETTI_URI, and has no
# default; without it onboarding is rejected with "pricing_strategy_code does not have a valid
# value").
#
# That leaves exactly one gap: current_credit_line_change_date, which only Fiserv's overnight
# processing sets, and which CreditCardAccount#onboarding_request_has_been_processed_by_fdr?
# checks. prepare! fills in that field and nothing else.
#
# ## It also forces the consolidated agreement
#
# prepare! tags the account needs_consolidated_cma and verify! refuses to return unless the
# resolved template is the consolidated one. The fee variables exist only there; _1 hardcodes
# $28/$39, so a Run on _1 reports backbook amounts for any pricing strategy and nothing errors
# (FINDINGS #21). The tag needs zzz_local_consolidated_cma.rb loaded to have any effect.
#
# ## Known limitation, not caused by this helper
#
# A locally-approved application has no product decision, so the
# Underwriting::ApplyDecisions::Card::Product data source logs "Invalid Data Source!
# annual_membership_fee_amount must be a float" and cma_apr_margin_decimal returns nil. Non-fatal.
# Fee assertions are unaffected (fees resolve from Confetti) and the margin is expected nil on a
# fixed-rate strategy, but do not trust it on a variable-rate one.
module LocalCmaStub
  class Error < StandardError; end

  # The only field this helper invents.
  ONBOARDING_MARKER = 'current_credit_line_change_date'.freeze
  STRATEGY_FIELD    = 'current_cardholder_pricing_strategy_identifier'.freeze

  # refresh_credit_card_cache_data_if_needed! discards final_account if either is missing.
  REQUIRED_RATES = %w[purchase_daily_rate cash_advance_daily_rate].freeze

  STRATEGY_TAG_KEY = 'avant_card_initial_strategy'.freeze

  # The fee content under test exists only on the consolidated agreement; _1 still hardcodes
  # $28/$39 (FINDINGS #21). Every Run must land here, whether it expects frontbook or backbook
  # amounts - a backbook expectation is only meaningful on the template the fees can appear on.
  CONSOLIDATED_TEMPLATE = :credit_card_cardmember_agreement_consolidated

  class << self
    # @param allow_unissued [Boolean] escape hatch; the payload is then whatever the account has,
    #   which for an unissued card means no real pricing strategy. You almost never want this.
    # @return [Hash] summary of what changed
    def prepare!(account, allow_unissued: false)
      guard_environment!
      cca = resolve(account)

      unless cca.status.to_s == 'issued' || allow_unissued
        raise Error, "cc account #{cca.id} is #{cca.status}, not issued. Run `cca.issue!` first - " \
                     'it creates the servicing account and puts the real pricing strategy on the ' \
                     'account. Pass allow_unissued: true only if you know why you want otherwise.'
      end

      payload = cca.account.to_h.deep_stringify_keys
      payload[ONBOARDING_MARKER] = Date.current.to_s
      backfill_rates!(cca, payload)
      backfilled_strategy = backfill_strategy!(cca, payload)

      cross_check_strategy!(cca, payload)

      # `.present?` is not enough: 0.0.present? is true, and an unonboarded account carries 0.0
      # rather than nil for every rate.
      missing = REQUIRED_RATES.reject { |k| payload[k].to_f.positive? }
      if missing.any?
        raise Error, "account payload has no usable #{missing.join(', ')} and none could be " \
                     'derived from the account. Was the onboarding call successful?'
      end

      cca.update!(final_account: payload)
      cca.invalidate_cached_account!

      # Opens the Optimizely guard too - see zzz_local_consolidated_cma.rb. Without this the
      # account renders _1 and reports $28/$39 for any pricing strategy.
      cca.add_scenario!(::CreditCardAccount::Scenarios::NEEDS_CONSOLIDATED_CMA)

      verify!(cca).merge(strategy_backfilled: backfilled_strategy)
    end

    def revert!(account)
      guard_environment!
      cca = resolve(account)
      cca.update!(final_account: nil)
      cca.remove_scenario!(::CreditCardAccount::Scenarios::NEEDS_CONSOLIDATED_CMA)
      cca.invalidate_cached_account!
      { credit_card_account_id: cca.id, stubbed: false, consolidated_cma_forced: false }
    end

    def status(account)
      cca = resolve(account)
      {
        credit_card_account_id: cca.id,
        product_status: cca.status,
        stubbed: cca.final_account.present?,
        pricing_strategy: safe { cca.current_cardholder_pricing_strategy_identifier },
        decisioned_pricing_strategy: decisioned_pricing_strategy(cca),
        onboarding_ok: safe { cca.onboarding_request_has_been_processed_by_fdr? },
        consolidated_cma_forced: cca.scenario_enabled?(::CreditCardAccount::Scenarios::NEEDS_CONSOLIDATED_CMA),
        show_consolidated_cma: safe { cca.show_consolidated_cma? },
        servicing_account: cca.servicing_account&.id,
        cma_template: safe { cca.servicing_account&.interface&.cardmember_agreement_template_name },
      }
    end

    private

    def guard_environment!
      return if Rails.env.development? || Rails.env.test?
      raise Error, "LocalCmaStub refuses to run in #{Rails.env}"
    end

    def resolve(account)
      return account if account.is_a?(CreditCardAccount)

      found =
        if account.is_a?(String) && account.include?('-')
          CreditCardAccount.find_by(uuid: account)
        else
          CreditCardAccount.find_by(id: account)
        end

      found || raise(Error, "no CreditCardAccount for #{account.inspect}")
    end

    # Fiserv sets the rate fields during overnight processing, so a freshly issued account has
    # 0.0 for every one of them and the CMA would render 0.00% APR. basic already holds the
    # decisioned values on its own columns (the same ones CSP shows), so use those rather than
    # letting a zero through. Only fills a field that is blank or zero; a real value always wins.
    def backfill_rates!(cca, payload)
      purchase = cca.apr_percentage&.to_f
      cash     = cca.cash_apr_percentage&.to_f || purchase

      set_if_unset(payload, 'purchase_apr',            purchase && (purchase * 100).round(2))
      set_if_unset(payload, 'maximum_merchandise_apr', purchase && (purchase * 100).round(2))
      set_if_unset(payload, 'cash_advance_apr',        cash && (cash * 100).round(2))
      set_if_unset(payload, 'purchase_daily_rate',        purchase && (purchase / 365))
      set_if_unset(payload, 'cash_advance_daily_rate',    cash && (cash / 365))
      set_if_unset(payload, 'credit_limit_cents',      cca.credit_line_amount_cents&.to_i)
      payload
    end

    # The pricing strategy is another field only Fiserv's overnight processing writes, so a
    # locally issued account carries none and the cross-check below has nothing to compare.
    # Fill it from the decision path tag - the record of what real decisioning actually priced
    # the application at - the same way backfill_rates! fills the rate fields from basic's own
    # decisioned columns.
    #
    # Returns whether it had to, so the caller can say so: a Run whose strategy was supplied
    # rather than read back from the account is weaker evidence, and the artifact must show it.
    def backfill_strategy!(cca, payload)
      return false if payload[STRATEGY_FIELD].present?

      expected = decisioned_pricing_strategy(cca)
      if expected.blank?
        raise Error, 'account payload carries no pricing strategy and the application has no ' \
                     'avant_card_initial_strategy decision path tag either, so there is nothing ' \
                     'to price the agreement from. Was the application decisioned?'
      end

      payload[STRATEGY_FIELD] = expected
      true
    end

    def set_if_unset(payload, key, value)
      return if value.nil?
      return if payload[key].present? && payload[key].to_f.positive?

      payload[key] = value
    end

    # Do not silently pin a payload whose strategy disagrees with what the application was
    # decisioned under - every fee assertion downstream would be measuring the wrong product.
    def cross_check_strategy!(cca, payload)
      expected = decisioned_pricing_strategy(cca)
      actual   = payload[STRATEGY_FIELD].presence
      return if expected.blank? || actual == expected

      raise Error, "account is priced at #{actual.inspect} but the application was decisioned " \
                   "under #{expected.inspect}. Refusing to pin a payload that would render the " \
                   'CMA under the wrong strategy.'
    end

    # The strategy the application was actually decisioned under.
    def decisioned_pricing_strategy(cca)
      app = cca.customer_application
      return nil unless app

      DecisionPathTag
        .where(customer_application_id: app.id, path_key: STRATEGY_TAG_KEY)
        .order(created_at: :desc)
        .first
        &.data
        &.dig('pricing_strategy_id')
        .presence
    end

    def verify!(cca)
      unless cca.onboarding_request_has_been_processed_by_fdr?
        raise Error, 'stub did not take: onboarding gate still closed'
      end

      # Assert the template rather than trusting the tag. The tag is one of three conditions
      # show_consolidated_cma? reads, and the render itself gives no hint which template it used.
      template = cca.servicing_account&.interface&.cardmember_agreement_template_name
      if template&.to_sym != CONSOLIDATED_TEMPLATE
        raise Error, "resolved CMA template is #{template.inspect}, not #{CONSOLIDATED_TEMPLATE}. " \
                     'Only the consolidated agreement carries the fee variables, so a render now ' \
                     'would report backbook amounts whatever the pricing strategy (FINDINGS #21). ' \
                     'Is zzz_local_consolidated_cma.rb loaded? Check the boot log for ' \
                     '[local] LocalConsolidatedCma.'
      end

      {
        credit_card_account_id: cca.id,
        stubbed: true,
        product_status: cca.status,
        pricing_strategy: cca.current_cardholder_pricing_strategy_identifier,
        onboarding_ok: true,
        cma_template: template,
        consolidated_cma_forced: true,
        revert_with: "LocalCmaStub.revert!(#{cca.id})",
      }
    end

    def safe
      yield
    rescue StandardError => e
      "#{e.class}: #{e.message[0, 80]}"
    end
  end
end
