# UNTRACKED local-only initializer for the frontbook fee launch validation. See FINDINGS #3, #33.
#
# Why this exists
# ---------------
# 12 of the 28 Runs are MLA variants (3M33, 3M32, 3M90, ...). They carry no strategy uuid and are
# never URL-selectable: onboarding derives them from the base code when the applicant is an MLA
# customer (lib/avant/decisioning/channels/onboarding.rb:123).
#
#   psc = PricingStrategies::Service.pricing_strategy_code_to_mla.fetch(psc, psc) if mla_customer?
#
# mla_customer? resolves to a positive TransUnion MLA report. Locally the MLA pull is served by
# the report-manager mock, NOT by TransUnion::Gateway.raw_test_data - the card policy answers true
# to pull_using_report_manager?(:transunion_mla) (app/models/customer_application/reports.rb:231),
# so the hardcoded :mla_negative_stub that FINDINGS #3 blamed is never reached on this flow.
#
# What the mock does instead is worse than a block: FakeTransunion#get_mla_report falls back to
# :transunion_mla_positive for every SSN outside its four-entry map, so locally EVERY applicant is
# a covered borrower. Verified 2026-09-02 on application 7, last name "approved": a positive MLA
# report (FINDINGS #33). That silently reprices any Run whose base code has an M variant - 12 of
# the 16 URL-reachable codes - and nothing errors: the Run asks for 3303 and issues under 3M33.
#
# What this changes
# -----------------
# get_mla_report keys off the applicant LAST NAME, the way the primary and secondary reports in
# the same class already do: a last name containing "mla" gets the positive fixture, everyone else
# gets the negative one. That makes MLA an explicit per-Run choice in both directions - the point
# is as much to keep the 16 base-code Runs honest as to make the 12 MLA Runs reachable.
#
# raw_test_data's transunion_mla branch is patched the same way, so a policy that does not use the
# report manager behaves identically rather than diverging silently. Nothing else is touched:
# pricing-strategy resolution, mla_customer? and the whole render path run unpatched, which is what
# keeps the evidence worth anything - the forged input is the applicant classification, upstream of
# everything under test.
#
# Use the last name "mlaapproved", not "mla": the primary report is served by the same class, which
# keys off the same last name and needs to see "approved" or the application declines before an MLA
# pull ever happens. Both matchers use include?, so one name drives both.
#
# LocalMlaStub.verify!(application, expected_code:) asserts the forcing actually took. Call it -
# the stub can be loaded and still resolve negative (no MLA pull performed, stale report, last name
# overwritten by a later autofill), and every one of those failures is silent: the Run simply
# prices under the base code and reports frontbook amounts for a code nobody asked about.
module LocalMlaStub
  class Error < StandardError; end

  MLA_LAST_NAME_IDENTIFIER = 'mla'.freeze

  # The path that actually fires on the card apply flow. Mirrors the last-name dispatch the
  # primary and secondary reports in the same class already use. The SSN map is deliberately
  # not consulted: its only entry forces a negative, which is now the default anyway.
  module ReportManagerPatch
    def get_mla_report(handler)
      last_name = handler.special_case_identifier.to_s
      file = if last_name.include?(LocalMlaStub::MLA_LAST_NAME_IDENTIFIER)
               :transunion_mla_positive
             else
               :transunion_mla_negative
             end

      self.class.load_report(file, report_type: :mla, object_uuid: object_uuid,
                                   applicant_data: applicant_data)
    end
  end

  # Mirrors the last-name override on the `transunion` branch of the same method.
  module GatewayPatch
    def raw_test_data(report_info)
      return super unless report_info.report_type == 'transunion_mla'

      last_name = report_info.customer.try(:person).try(:last_name).to_s.downcase
      return super unless last_name.include?(LocalMlaStub::MLA_LAST_NAME_IDENTIFIER)

      TransUnion::DataStub.mla_positive_stub
    end
  end

  class << self
    # @return [Hash] what the application actually resolved to
    def status(application)
      app = resolve(application)
      {
        customer_application_id: app.id,
        last_name: app.customer&.person&.last_name,
        mla_report_id: mla_report(app)&.id,
        military_lending_act_confirmed: safe { mla_confirmed?(app) },
        military_lending_act_relevant: safe { app.decisioning_interface.military_lending_act_relevant? },
        base_strategy: base_strategy(app),
        mla_strategy: safe { mapped_strategy(app) },
      }
    end

    # Asserts both halves of DESIGN decision 7: the report came back positive, AND the strategy the
    # account will open under is the MLA code. Either alone can pass while the other does not.
    #
    # @param expected_code [String] the MLA code the Run is validating, e.g. "3M33"
    def verify!(application, expected_code:)
      app = resolve(application)

      report = mla_report(app)
      if report.nil?
        raise Error, "application #{app.id} has no TransUnion MLA report at all, so nothing was " \
                     'forced. Was the last name set to mlaapproved before the personal stage ' \
                     'was submitted?'
      end

      unless mla_confirmed?(app)
        raise Error, "MLA report #{report.id} reads military_lending_act_confirmed=false. The " \
                     'negative fixture was served: check the boot log for [local] LocalMlaStub ' \
                     "and that the last name (#{app.customer&.person&.last_name.inspect}) " \
                     "contains #{MLA_LAST_NAME_IDENTIFIER.inspect} (FINDINGS #3)."
      end

      unless app.decisioning_interface.military_lending_act_relevant?
        raise Error, 'the report is positive but military_lending_act_relevant? is false, so ' \
                     'onboarding will not apply the MLA mapping. The report is probably stale ' \
                     'or belongs to a different customer.'
      end

      resolved = mapped_strategy(app)
      unless resolved.to_s == expected_code.to_s
        raise Error, "MLA mapping resolves #{base_strategy(app).inspect} to #{resolved.inspect}, " \
                     "not the expected #{expected_code.inspect}. Either the application was " \
                     'decisioned under the wrong base code, or Confetti ' \
                     'pricing_strategy_code_to_mla disagrees with data/run-matrix.csv.'
      end

      {
        customer_application_id: app.id,
        mla_forced: true,
        mla_report_id: report.id,
        base_strategy: base_strategy(app),
        pricing_strategy: resolved,
      }
    end

    private

    def resolve(application)
      return application if application.is_a?(CustomerApplication)

      found =
        if application.is_a?(String) && application.include?('-')
          CustomerApplication.find_by(uuid: application)
        else
          CustomerApplication.find_by(id: application)
        end

      found || raise(Error, "no CustomerApplication for #{application.inspect}")
    end

    def mla_report(app)
      app.customer&.relevant_transunion_mla_report
    end

    def mla_confirmed?(app)
      summary = mla_report(app)&.transunion_secondary_summary
      !!summary&.military_lending_act_confirmed
    end

    def base_strategy(app)
      DecisionPathTag::PathTags::AvantCardInitialStrategy.persisted_strategy_id(app)
    end

    # The same fetch onboarding performs, read rather than reimplemented, so a Confetti change
    # shows up here as a failure instead of being masked by a local copy of the mapping.
    def mapped_strategy(app)
      base = base_strategy(app)
      return nil if base.blank?

      PricingStrategies::Service.pricing_strategy_code_to_mla.fetch(base, base)
    end

    def safe
      yield
    rescue StandardError => e
      "#{e.class}: #{e.message[0, 80]}"
    end
  end
end

# Gate it explicitly so it cannot fire anywhere but a local box: it forges an applicant's military
# status, which drives pricing.
if Rails.env.development? && Avant::Env.enable_mock_services?
  require 'avant/trans_union/gateway'
  require Rails.root.join('spec/support/rails/mock_services/report_manager/transunion.rb')

  mock = Support::MockServices::ReportManager::FakeTransunion
  unless mock.include?(LocalMlaStub::ReportManagerPatch)
    mock.prepend(LocalMlaStub::ReportManagerPatch)
  end

  unless TransUnion::Gateway.singleton_class.include?(LocalMlaStub::GatewayPatch)
    TransUnion::Gateway.singleton_class.prepend(LocalMlaStub::GatewayPatch)
  end

  Rails.logger.info(
    '[local] LocalMlaStub active - only a last name containing "mla" gets a positive MLA report'
  )
end
