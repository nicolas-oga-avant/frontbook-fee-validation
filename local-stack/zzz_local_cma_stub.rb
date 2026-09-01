# UNTRACKED local-only helper (CSRV-5300 validation). See FINDINGS #15.
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

      verify!(cca)
    end

    def revert!(account)
      guard_environment!
      cca = resolve(account)
      cca.update!(final_account: nil)
      cca.invalidate_cached_account!
      { credit_card_account_id: cca.id, stubbed: false }
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

      {
        credit_card_account_id: cca.id,
        stubbed: true,
        product_status: cca.status,
        pricing_strategy: cca.current_cardholder_pricing_strategy_identifier,
        onboarding_ok: true,
        cma_template: cca.servicing_account&.interface&.cardmember_agreement_template_name,
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
