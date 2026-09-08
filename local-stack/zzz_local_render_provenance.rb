# UNTRACKED local-only initializer for the frontbook fee launch validation. See FINDINGS #22, #34
# and hard rule 3 in AGENTS.md.
#
# Why this exists
# ---------------
# Every Run renders against PRODUCTION TemplateFlow, and what makes that safe - and what makes it
# pick up the fee content under test at all - is the pair of flags basic sends:
#
#   preview          keeps the render from persisting a document to production
#   allow_unapproved makes TemplateFlow serve the newest DRAFT rather than the newest APPROVED
#
# Both default to !Avant::Env.acts_as_prod? (lib/avant/templateflow/create_document.rb:18-19), so
# they are on locally and nothing in the render output says so. Two silent failures follow:
#
#   preview off          -> drafts stop rendering AND documents start persisting to production
#   allow_unapproved off -> TemplateFlow answers with the newest approved version. Before CSRV-5895
#                           that has no fee variables and hardcodes $28/$39 (FINDINGS #22), and a
#                           frontbook Run then reports backbook amounts and nothing errors.
#
# CSRV-5895 (approve template 9658 v7) can land at any time - the launch runbook does not gate it
# on this repo, and once it lands, forcing allow_unapproved forever becomes its own silent failure
# the other direction: it would keep testing whatever the newest DRAFT is, even after production no
# longer needs one, and would silently follow a future unrelated draft (v8, v9...) if one is ever
# opened on this template for other work. So the correct flag is not a constant - it is whatever
# TemplateFlow's approved side currently serves, checked fresh, every render (FINDINGS #34).
#
# What this changes
# -----------------
# Prepends onto Avant::Templateflow::CreateDocument to do three things per call:
#
#   1. Refuse the request outright unless preview is on - before it is sent, so no document can
#      ever persist to production.
#   2. Check, fresh and uncached, whether the currently APPROVED version already carries all three
#      fee variables. If the check itself fails, halt rather than guess (AGENTS.md hard rule: assume
#      silence means failure applies here too - a broken check is not evidence either way).
#   3. Force allow_unapproved to the opposite of that answer - true (draft) while unapproved, false
#      (approved) once it is not - overriding whatever the caller passed, so no other file has to
#      know or guess CSRV-5895's status. Records the provenance the response carries plus which
#      render_mode was used, so LocalCmaRender can stamp it onto the Run.
#
# Scoped to the cardmember agreement templates on purpose. Loan contracts legitimately render with
# preview: false (app/models/loan_contract.rb:601,715), and a global raise would break unrelated
# flows in the web process - a mechanical failure with a confusing message.
module LocalRenderProvenance
  class UnsafeRender < StandardError; end
  class ApprovalCheckFailed < StandardError; end

  # The variables that only exist once the fee-launch content is live on a version. Require all
  # three, not any: a partially-approved draft should still count as "not ready" (AGENTS.md hard
  # rule: never trust a value because it looks plausible).
  FEE_VARIABLES = %w[late_fee_initial late_fee_subsequent foreign_transaction_fee].freeze

  # config/policies/documents/letters/avant_card_us.yml:107-118. The consolidated one is the
  # template under test; the other two are here so a Run that lands on the wrong template is
  # still guarded rather than silently unguarded.
  CMA_TEMPLATE_UUIDS = {
    '806c523b-7be2-47de-8c3c-863c77a7fc77' => :credit_card_cardmember_agreement_0,
    '0b480903-330d-42cd-9cb5-7cff942c44f9' => :credit_card_cardmember_agreement_1,
    '5d5b0b5c-9e69-4bb4-aaa5-68581f7e7c93' => :credit_card_cardmember_agreement_consolidated,
  }.freeze

  MAX_CALLS = 50

  class << self
    def cma_template?(uuid)
      CMA_TEMPLATE_UUIDS.key?(uuid.to_s)
    end

    def assert_preview!(uuid:, preview:)
      return if preview

      raise UnsafeRender,
            "refusing to render cardmember agreement template #{uuid} with preview=false. " \
            'preview keeps the render from persisting a document to production TemplateFlow. ' \
            "It defaults to !Avant::Env.acts_as_prod?, currently #{!Avant::Env.acts_as_prod?} - " \
            'so check what made this stack acts_as_prod?.'
    end

    # Fresh, uncached: bypasses avant-basic's own Caches::Templates (used by
    # Avant::Templateflow::GetVariables) on purpose, and calls the raw client rather than
    # GetVariables so allow_unapproved: false cannot be overridden by that action's own default of
    # !Avant::Env.acts_as_prod?. Every render re-checks; nothing here is memoized across Runs,
    # because the answer can change mid-Campaign the moment someone clicks approve.
    #
    # @return [Boolean] true if the approved version already carries all three fee variables
    def approved_version_carries_fee_content?(uuid)
      resp = TemplateflowEngine::Client.get_variables(
        template_uuid: uuid, identifier: nil, allow_unapproved: false,
      ).response

      raise ApprovalCheckFailed, "nil response checking approved variables for #{uuid}" if resp.nil?
      raise ApprovalCheckFailed, "error checking approved variables for #{uuid}: #{resp[:error]}" if resp[:error]

      variables = resp[:variables] || resp['variables']
      raise ApprovalCheckFailed, "no variables list in approved-version response for #{uuid}" if variables.nil?

      present = variables.map(&:to_s)
      FEE_VARIABLES.all? { |v| present.include?(v) }
    rescue ApprovalCheckFailed
      raise
    rescue StandardError => e
      raise ApprovalCheckFailed, "could not check approved version for #{uuid}: #{e.class}: #{e.message}"
    end

    # Decides which flag the render actually needs, checked fresh against TemplateFlow, and
    # returns it. Raises rather than guessing if the check itself is unreliable - a Run should
    # halt on an unknown approval state, not assume either direction (AGENTS.md: assume silence
    # means failure).
    #
    # @return [Boolean] the allow_unapproved value this render must use
    def resolve_allow_unapproved!(uuid:)
      !approved_version_carries_fee_content?(uuid)
    end

    def record(entry)
      mutex.synchronize do
        calls_store << entry
        calls_store.shift while calls_store.size > MAX_CALLS
      end
      entry
    end

    def calls
      mutex.synchronize { calls_store.dup }
    end

    def last
      calls.last
    end

    def reset!
      mutex.synchronize { calls_store.clear }
      true
    end

    def host
      ENV['AVANT_TEMPLATES_HOST']
    end

    private

    def mutex
      @mutex ||= Mutex.new
    end

    def calls_store
      @calls_store ||= []
    end
  end

  module Probe
    def call
      return super unless LocalRenderProvenance.cma_template?(uuid)

      LocalRenderProvenance.assert_preview!(uuid: uuid, preview: preview)

      # Not a caller decision: force the flag this render actually needs, regardless of what was
      # passed in or what !Avant::Env.acts_as_prod? would otherwise default it to. See the module
      # doc comment and FINDINGS #34 - the correct value depends on live TemplateFlow state, not
      # on anything this process already believes.
      needed = LocalRenderProvenance.resolve_allow_unapproved!(uuid: uuid)
      instance_variable_set(:@allow_unapproved, needed) if allow_unapproved != needed

      super.tap do |body|
        LocalRenderProvenance.record(
          template_id:           uuid.to_s,
          template_name:         LocalRenderProvenance::CMA_TEMPLATE_UUIDS[uuid.to_s],
          template_version_id:   body[:template_version_uuid],
          all_version_uuids:     body[:all_version_uuids],
          preview:               preview,
          allow_unapproved:      needed,
          render_mode:           needed ? 'draft' : 'approved',
          templateflow_host:     LocalRenderProvenance.host,
          rendered_at:           Time.current.iso8601,
        )
      end
    end
  end
end

if Rails.env.development?
  Rails.application.config.to_prepare do
    # lib/ is not autoloaded, so the constant may not exist yet when this initializer runs.
    require 'avant/templateflow/create_document'

    klass = Avant::Templateflow::CreateDocument
    unless klass.included_modules.include?(LocalRenderProvenance::Probe)
      klass.prepend(LocalRenderProvenance::Probe)
    end
  end

  Rails.logger.info(
    '[local] LocalRenderProvenance active - CMA renders assert preview + allow_unapproved and ' \
    'record the template version'
  )
end
