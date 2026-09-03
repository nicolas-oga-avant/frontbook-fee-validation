# UNTRACKED local-only helper for the frontbook fee launch validation. See FINDINGS #5, #34.
#
# Collects the four assertion points that can only be read from inside the stack, and writes them
# as the observations.json that scripts/assert_value_table.py asserts against.
#
#   LocalRunObservations.collect!(account: cca.id, application: app_id, code: '0122')
#   LocalRunObservations.collect!(account: cca.id, application: app_id, code: '0122',
#                                 out_dir: '/usr/src/app/tmp', rendered_html: 'cma_0122_log2.html')
#
# Why a file rather than four console reads
# -----------------------------------------
# The value table has five points and a Run that renders the agreement has tested one of them.
# Reading the other four by hand produces numbers in a transcript, which is not evidence and
# cannot be re-asserted later. This writes them once, in a shape the assertion script owns.
#
# Nothing here decides whether a value is right. Every expectation lives in run-matrix.csv and is
# applied outside the stack, so a wrong value gets recorded and reported rather than corrected on
# the way out (hard rule 2).
module LocalRunObservations
  class Error < StandardError; end

  DEFAULT_OUT_DIR = '/usr/src/app/tmp'.freeze

  # How old a process may be before its Optimizely reads stop counting as fresh. The RPF amounts
  # come from a polled datafile and are memoised per CreditCardAccount instance, so a console that
  # has been open since before a datafile change keeps serving the old ones (FINDINGS #5).
  FRESH_PROCESS_SECONDS = 300

  LOADED_AT = Time.now

  class << self
    # @param account [CreditCardAccount, Integer, String] account, id or uuid
    # @param application [CustomerApplication, Integer] the application the Run walked, by explicit id
    # @param code [String] the pricing strategy this Run is for
    # @param rendered_html [String, nil] path to the rendered agreement, recorded so the
    #   assertion script asserts the same document this collection describes
    # @return [Hash] the observations, also written to <out_dir>/observations.json
    def collect!(account:, application:, code:, out_dir: DEFAULT_OUT_DIR, rendered_html: nil)
      guard_environment!
      cca = resolve_account(account)
      app = resolve_application(application)
      errors = {}

      observations = {
        code:              code.to_s,
        collected_at:      Time.now.utc.iso8601,
        credit_card_account_id: cca.id,
        application_id:    app.id,
        application:       capture(errors, :application) { application_terms(app) },
        agreement_inputs:  capture(errors, :agreement_inputs) { agreement_inputs(cca) },
        csp:               capture(errors, :csp) { csp_labels(cca) },
        rpf:               capture(errors, :rpf) { rpf(cca) },
        rendered:          rendered_html ? { html: rendered_html } : nil,
        errors:            errors,
      }

      assert_strategy!(cca, code)
      write!(observations, out_dir)
    end

    private

    def guard_environment!
      return if Rails.env.development? || Rails.env.test?
      raise Error, "LocalRunObservations refuses to run in #{Rails.env}"
    end

    def resolve_account(account)
      return account if account.is_a?(CreditCardAccount)

      found =
        if account.is_a?(String) && account.include?('-')
          CreditCardAccount.find_by(uuid: account)
        else
          CreditCardAccount.find_by(id: account)
        end
      found || raise(Error, "no CreditCardAccount for #{account.inspect}")
    end

    def resolve_application(application)
      return application if application.is_a?(CustomerApplication)

      found =
        if application.is_a?(String) && application.include?('-')
          CustomerApplication.find_by(uuid: application)
        else
          CustomerApplication.find_by(id: application)
        end

      found || raise(Error, "no CustomerApplication for #{application.inspect}")
    end

    # The Run's identity. Collecting observations for one code and asserting them as another is
    # the same contamination hard rule 1 exists to prevent, so it is refused here rather than
    # noticed later in a diff.
    def assert_strategy!(cca, code)
      actual = cca.current_cardholder_pricing_strategy_identifier.to_s
      return if actual == code.to_s

      raise Error, "account #{cca.id} is priced at #{actual.inspect}, not the #{code.to_s.inspect} " \
                   'these observations would be filed under.'
    end

    # A section that raises is recorded as an error and leaves its point uncaptured, which the
    # assertion script fails on. Swallowing it would leave a point looking asserted.
    def capture(errors, key)
      yield
    rescue StandardError => e
      errors[key] = "#{e.class}: #{e.message}"
      nil
    end

    # What the applicant was quoted, read back from the stored applicant data rather than
    # recomputed - recomputing would report what the code would say today, not what the walk saw.
    def application_terms(app)
      {
        decision_path_strategy: ::DecisionPathTag::PathTags::AvantCardInitialStrategy.strategy_id(app),
        predecisioned_terms:    app.o_api.applicant_interface.get(:predecisioned_terms),
      }
    end

    def agreement_inputs(cca)
      {
        cma_pricing_strategy_identifier: cca.cma_pricing_strategy_identifier,
        cma_fee_terms:                   cca.cma_fee_terms,
      }
    end

    def csp_labels(cca)
      {
        late_fee_structure:      cca.late_fee_structure,
        foreign_transaction_fee: cca.foreign_transaction_fee,
      }
    end

    def rpf(cca)
      config = cca.rpf_configuration
      age = Time.now - LOADED_AT
      config.merge(
        fee_eligible:  cca.rpf_fee_eligible?,
        fresh_process: !defined?(Rails::Console) && age < FRESH_PROCESS_SECONDS,
        process_age_seconds: age.round,
        **optimizely_source
      )
    end

    # Where the flag values came from. Without an sdk key the client is built from a datafile
    # COMMITTED to the repo (config/initializers/129_optimizely.rb:37), so it answers from a
    # snapshot taken whenever someone last refreshed that file - which is how a correct account
    # reads as RPF-ineligible with no error. A Run cannot tell the two apart from the values.
    def optimizely_source
      { sdk_key_present: Avant::Env.optimizely_sdk_key.present?,
        datafile_revision: datafile_revision }
    end

    def datafile_revision
      path = Rails.root.join('config', 'optimizely', Rails.env, 'datafile.json')
      path = Rails.root.join('config', 'optimizely', 'datafile.json') unless File.exist?(path)
      JSON.parse(File.read(path))['revision']
    rescue StandardError => e
      "unreadable: #{e.class}"
    end

    def write!(observations, out_dir)
      FileUtils.mkdir_p(out_dir)
      path = File.join(out_dir, "observations_#{observations[:code]}.json")
      File.write(path, JSON.pretty_generate(observations))
      observations.merge(file: path)
    end
  end
end

Rails.logger.info(
  '[local] LocalRunObservations active - collect!(account:, application:, code:) writes the ' \
  'value-table observations'
)
