# One rails-runner pass through approve -> issue -> render -> observe, consolidating the
# console steps in surfaces/cma.md Step 4 into a single script instead of several separate
# `rails runner` invocations. Nothing here decides pass/fail (hard rule 2 in AGENTS.md) - it
# runs the same calls a console session already made by hand, in the same order, and raises
# with whatever Ruby raised if a step fails. That exception IS the evidence; do not rescue it
# away to make the script "succeed".
#
#   docker compose -p "$BASIC_PROJECT" exec -T web bundle exec rails runner \
#     /usr/src/app/tmp/console_runner.rb <CODE> <APPLICATION_UUID> [MLA_BASE_CODE]
#
# MLA_BASE_CODE is only needed for an MLA-forced Run: pass it (e.g. "7213" for 7M83) to
# trigger the TransUnion MLA report pull before LocalMlaStub.verify! runs - product.approve!
# alone never pulls it locally (FINDINGS #37). Omit it entirely for a direct code; passing an
# empty string also skips it.
#
# Prints one JSON object between APPLY_RESULT_JSON_START/END with everything a caller needs
# to pull evidence out of the container: credit_card_account_id, both agreement log ids, the
# render provenance, and the observations file path.

require "json"

OptimizelyInitializer.setup!

code, app_uuid, mla_base_code = ARGV
raise "usage: console_runner.rb <CODE> <APPLICATION_UUID> [MLA_BASE_CODE]" if code.nil? || app_uuid.nil?

mla_forced = mla_base_code.present?

app = CustomerApplication.find_by!(uuid: app_uuid)

# FINDINGS #37: the MLA report is pulled by the New Verifications identity-verification loop
# (PullAllReports, behind the /verify/<uuid> redirect this stack does not run), never by
# product.approve! itself. Trigger it directly - zzz_local_mla_stub.rb's get_mla_report patch
# already intercepts it by last name.
app.run_transunion_mla_report!(force: true) if mla_forced

prod = app.product
prod.approve!
cca_id = prod.id

mla_result =
  if mla_forced
    LocalMlaStub.verify!(app, expected_code: code)
  end

cca = CreditCardAccount.find(cca_id)

# Capture the issuance log by diffing ids around issue!, never by .last (hard rule 1) - an
# account can accumulate several logs and picking the wrong one silently validates a
# different document.
before_log_ids = CardmemberAgreementLog.where(credit_card_account_id: cca.id).pluck(:id)
cca.issue!
cca.reload
new_log_ids = CardmemberAgreementLog.where(credit_card_account_id: cca.id).pluck(:id) - before_log_ids
unless new_log_ids.size == 1
  raise "expected exactly one new CardmemberAgreementLog from issue!, got #{new_log_ids.inspect}"
end
issuance_log = CardmemberAgreementLog.find(new_log_ids.first)

prepare_result = LocalCmaStub.prepare!(cca.id)

strategy = cca.reload.current_cardholder_pricing_strategy_identifier.to_s
raise "wrong strategy: expected #{code}, got #{strategy.inspect}" unless strategy == code

render_log = CardmemberAgreementLog.create!(
  credit_card_account: cca,
  reason_type: CardmemberAgreementLog::CSP_REQUESTED,
  template_variables: issuance_log.template_variables,
)

out_dir = "/usr/src/app/tmp/run-#{code}"
provenance = LocalCmaRender.call!(cca.id, log_id: render_log.id, expected_code: code, out_dir: out_dir)

observations = LocalRunObservations.collect!(
  account: cca.id,
  application: app.id,
  code: code,
  out_dir: out_dir,
  rendered_html: File.basename(provenance[:files][:html]),
)

result = {
  code: code,
  application_id: app.id,
  application_uuid: app_uuid,
  credit_card_account_id: cca.id,
  mla_forced: mla_forced,
  mla_result: mla_result,
  issuance_log_id: issuance_log.id,
  agreement_log_id: render_log.id,
  prepare_result: prepare_result,
  provenance: provenance,
  observations_file: observations[:file],
  out_dir: out_dir,
}

puts "CONSOLE_RESULT_JSON_START"
puts JSON.pretty_generate(result)
puts "CONSOLE_RESULT_JSON_END"
