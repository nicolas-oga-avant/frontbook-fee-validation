# UNTRACKED local-only initializer for the frontbook fee launch validation. See FINDINGS #21.
#
# Why this exists
# ---------------
# The frontbook fee content lives ONLY on the consolidated cardmember agreement (template 9658,
# 5d5b0b5c-9e69-4bb4-aaa5-68581f7e7c93). credit_card_cardmember_agreement_1 has none of the fee
# variables and still hardcodes $28/$39. So a Run that renders _1 reports backbook amounts for a
# frontbook pricing strategy, and nothing fails - the worst possible outcome here.
#
# Which template basic picks comes from show_consolidated_cma?
# (app/models/credit_card_account/cardmember_agreement_inputs.rb):
#
#   return false unless consolidated_cma_enabled?          # Optimizely
#   cutoff_date = Avant::Env::CardmemberAgreement.consolidated_cma_cutoff_date
#   (cutoff_date && issued_at > cutoff_date) || scenario_enabled?(NEEDS_CONSOLIDATED_CMA)
#
# The scenario tag sits INSIDE the OR, behind the Optimizely guard - so tagging an account is not
# enough on its own. Locally there is no Optimizely client at all (FINDINGS #16), so the guard is
# what actually closes the door.
#
# What this changes
# -----------------
# consolidated_cma_enabled? returns true for accounts carrying the needs_consolidated_cma tag, and
# defers to the real implementation for every other account. The tag stays the only switch, which
# is deliberate: a global override would silently apply to accounts a Run never prepared, and an
# env-var gate would add a second way to forget (unset var -> renders _1 -> false backbook pass).
# LocalCmaStub.prepare! sets the tag and asserts the resolved template name afterwards.
#
# CONSOLIDATED_CMA_CUTOFF_DATE is left alone on purpose. Setting it would flip every locally
# issued account at once, including any a backbook Run wants on the old template.
module LocalConsolidatedCma
  def consolidated_cma_enabled?
    return true if scenario_enabled?(::CreditCardAccount::Scenarios::NEEDS_CONSOLIDATED_CMA)

    super
  end
end

if Rails.env.development?
  Rails.application.config.to_prepare do
    unless CreditCardAccount.included_modules.include?(LocalConsolidatedCma)
      CreditCardAccount.prepend(LocalConsolidatedCma)
    end
  end

  Rails.logger.info(
    '[local] LocalConsolidatedCma active - needs_consolidated_cma tag forces the consolidated CMA'
  )
end
