# UNTRACKED local-only initializer for the frontbook fee launch validation. See FINDINGS #22 and
# hard rule 3 in AGENTS.md.
#
# Why this exists
# ---------------
# Every Run renders against PRODUCTION TemplateFlow, and what makes that safe - and what makes it
# pick up the v7 draft under test at all - is the pair of flags basic sends:
#
#   preview          keeps the render from persisting a document to production
#   allow_unapproved makes TemplateFlow serve the newest DRAFT rather than the newest APPROVED
#
# Both default to !Avant::Env.acts_as_prod? (lib/avant/templateflow/create_document.rb:18-19), so
# they are on locally and nothing in the render output says so. Two silent failures follow:
#
#   preview off          -> drafts stop rendering AND documents start persisting to production
#   allow_unapproved off -> TemplateFlow answers with v6, the newest approved version, which has
#                           no fee variables and still hardcodes $28/$39 (FINDINGS #22). A
#                           frontbook Run then reports backbook amounts and nothing errors.
#
# The second is the worse one, because it is indistinguishable from a real backbook result.
#
# What this changes
# -----------------
# Prepends onto Avant::Templateflow::CreateDocument to do two things per call:
#
#   1. Refuse the request outright unless both flags are on - before it is sent, so nothing
#      reaches production TemplateFlow and no document can persist.
#   2. Record the provenance the response carries (template_version_uuid, all_version_uuids) with
#      the flags actually used, so LocalCmaRender can stamp it onto the Run.
#
# Scoped to the cardmember agreement templates on purpose. Loan contracts legitimately render with
# preview: false (app/models/loan_contract.rb:601,715), and a global raise would break unrelated
# flows in the web process - a mechanical failure with a confusing message.
module LocalRenderProvenance
  class UnsafeRender < StandardError; end

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

    def assert_draft_preview!(uuid:, preview:, allow_unapproved:)
      return if preview && allow_unapproved

      raise UnsafeRender,
            "refusing to render cardmember agreement template #{uuid} with " \
            "preview=#{preview.inspect} allow_unapproved=#{allow_unapproved.inspect}. " \
            'Both must be on: preview keeps the render from persisting to production ' \
            'TemplateFlow, and allow_unapproved is what serves the draft under test instead of ' \
            'the newest approved version, which has no fee variables and hardcodes $28/$39 ' \
            "(FINDINGS #22). Both default to !Avant::Env.acts_as_prod?, currently " \
            "#{!Avant::Env.acts_as_prod?} - so check what made this stack acts_as_prod?."
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

      LocalRenderProvenance.assert_draft_preview!(
        uuid: uuid, preview: preview, allow_unapproved: allow_unapproved,
      )

      super.tap do |body|
        LocalRenderProvenance.record(
          template_id:           uuid.to_s,
          template_name:         LocalRenderProvenance::CMA_TEMPLATE_UUIDS[uuid.to_s],
          template_version_id:   body[:template_version_uuid],
          all_version_uuids:     body[:all_version_uuids],
          preview:               preview,
          allow_unapproved:      allow_unapproved,
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
