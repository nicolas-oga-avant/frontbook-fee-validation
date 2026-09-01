# UNTRACKED local-only initializer (CSRV-5300 validation).
#
# Why this exists
# ---------------
# Locally Avant::Env.transunion_url falls through to the deliberately fake
# 'https://netaccess.not_real_testing.com' (lib/avant/env.rb:1424), so the report-manager
# TransUnion gateway cannot connect, synthesises its invented error code 999
# (gateway.rb#exception_response), and every card application declines with
# `missing_transunion_report` before it ever reaches the reports stage.
#
# config/initializers/mock_services.rb already sets up WebMock for development but only
# registers the avant_card mocks - its own comment calls itself "a first pass ... We'll
# expand on this if it proves useful". Support::MockServices::ReportManager::FakeTransunion
# is already in the tree and unused. This registers it without editing that tracked file,
# which matters because the checkout is shared with other sessions.
#
# The filename starts with zzz so it loads AFTER mock_services.rb, which is what enables
# WebMock and defines the registry.
#
# How to drive it
# ---------------
# FakeTransunion keys its response off the applicant's LAST NAME:
#
#   approved              -> approved report (use this for the CSRV-5300 runs)
#   declined              -> declined report
#   freeze                -> security freeze
#   initialfcra           -> initial FCRA alert
#   extendedfcra          -> extended FCRA alert
#   nosubjectfoundmessage -> No Subject Found
#   missing               -> no report at all
#
# So the apply-flow autofill's random last name must be overwritten with `approved`.
#
# Gate it explicitly so it cannot fire anywhere but a local box.
if Rails.env.development? &&
   Avant::Env.enable_mock_services? &&
   ENV['MOCK_TRANSUNION'] == '1'

  require Rails.root.join('spec/support/rails/mock_services/report_manager/transunion.rb')

  Support::MockServices::Registry.mock([{ transunion: [type: :record_found] }])

  Rails.logger.info('[local] FakeTransunion mock registered - last name drives the report')
end
