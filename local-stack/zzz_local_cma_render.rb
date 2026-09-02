# UNTRACKED local-only helper for the frontbook fee launch validation. See FINDINGS #19, #21, #27.
#
# Renders one cardmember agreement and returns its provenance, which is the part a Run cannot be
# trusted without: the template the render actually resolved to, and the template VERSION the
# render actually used.
#
#   LocalCmaStub.prepare!(cca.id)                      # first - Fiserv fields, consolidated tag
#   LocalCmaRender.call!(cca.id, log_id: 1)            # renders, asserts, writes evidence
#   LocalCmaRender.call!(cca.id, log_id: 1, expected_code: '0122')
#
# Why a helper rather than four console lines
# -------------------------------------------
# The render is where every wrong answer in this campaign comes from, and none of it is visible in
# the output:
#
#   - a Run on credit_card_cardmember_agreement_1 reports $28/$39 for any pricing strategy,
#     because _1 has none of the fee variables (FINDINGS #21)
#   - a render without allow_unapproved gets the newest APPROVED version, which also has none of
#     them (FINDINGS #22) - enforced in zzz_local_render_provenance.rb
#   - a document is only attributable to a version, not a template: 9658 has seven of them and
#     only the v7 draft carries the new content (FINDINGS #22)
#
# So: assert the template by name and by uuid, and stamp the version id the render returned.
# Recording the template alone is not provenance.
#
# Correction to FINDINGS #28: the letter path DOES expose the version. cardmember_agreement_logs
# has a template_version_id column and CardmemberAgreementLetter#render_from_templateflow!
# (lib/avant/servicing_v2/communications/cardmember_agreement_letter.rb) writes the response's
# template_version_uuid to it. This helper reads it back and cross-checks it against what the
# probe saw on the wire, so a stale column cannot pass for a fresh render.
module LocalCmaRender
  class Error < StandardError; end

  CONSOLIDATED_TEMPLATE = :credit_card_cardmember_agreement_consolidated

  # Template 9658. Asserted rather than only read from config, so a config edit cannot quietly
  # repoint a Run at another template.
  CONSOLIDATED_TEMPLATE_ID = '5d5b0b5c-9e69-4bb4-aaa5-68581f7e7c93'.freeze

  DEFAULT_OUT_DIR = '/usr/src/app/tmp'.freeze

  class << self
    # @param account [CreditCardAccount, Integer, String] account, id or uuid
    # @param log_id [Integer] the agreement log to render, captured explicitly at creation.
    #   Required: an account accumulates several and picking by recency validates a different
    #   document (hard rule 1).
    # @param expected_code [String, nil] the pricing strategy the Run is for. Given, it is
    #   asserted against the account before the render.
    # @param out_dir [String] where the html, pdf and provenance.json are written
    # @return [Hash] provenance, also written to <out_dir>/provenance.json
    def call!(account, log_id:, expected_code: nil, out_dir: DEFAULT_OUT_DIR)
      guard_environment!
      cca = resolve(account)

      strategy = cca.current_cardholder_pricing_strategy_identifier.to_s
      assert_strategy!(strategy, expected_code)

      template_name = resolved_template_name(cca)
      template_id   = assert_template!(cca, template_name)

      log = resolve_log!(cca, log_id)
      ensure_template_variables!(cca, log)

      LocalRenderProvenance.reset!
      Avant::ServicingV2::Communications::CardmemberAgreementLetter.render_pdf(
        cardmember_agreement_log: log,
        template_name: template_name,
      )
      log.reload

      provenance = provenance_for(cca, log, strategy, template_name, template_id)
      write_evidence!(log, provenance, out_dir)
    end

    private

    def guard_environment!
      return if Rails.env.development? || Rails.env.test?
      raise Error, "LocalCmaRender refuses to run in #{Rails.env}"
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

    # The strategy is the product being validated. It is not on the document and the CSP never
    # shows it, so an unasserted Run cannot say which product its evidence is about.
    def assert_strategy!(strategy, expected_code)
      raise Error, 'account carries no pricing strategy. Run LocalCmaStub.prepare! first' if strategy.empty?
      return if expected_code.nil? || strategy == expected_code.to_s

      raise Error, "account is priced at #{strategy.inspect}, not the #{expected_code.inspect} " \
                   'this Run is for. Rendering now would produce evidence for the wrong product.'
    end

    def resolved_template_name(cca)
      cca.servicing_account&.interface&.cardmember_agreement_template_name&.to_sym ||
        raise(Error, "account #{cca.id} resolves no cardmember agreement template. Is it issued?")
    end

    # Two assertions, not one. The name proves show_consolidated_cma? took effect; the uuid proves
    # the name still points at template 9658.
    def assert_template!(cca, template_name)
      if template_name != CONSOLIDATED_TEMPLATE
        raise Error, "resolved CMA template is #{template_name.inspect}, not " \
                     "#{CONSOLIDATED_TEMPLATE}. Only the consolidated agreement carries the fee " \
                     'variables, so this render would report backbook amounts whatever the ' \
                     'pricing strategy (FINDINGS #21). Did LocalCmaStub.prepare! run, and is ' \
                     'zzz_local_consolidated_cma.rb loaded? Check the boot log for ' \
                     '[local] LocalConsolidatedCma.'
      end

      config = cca.config.documents.letters.try(template_name)
      raise Error, "no letter config for #{template_name}" unless config

      template_id = config.templateflow_uuid.to_s
      return template_id if template_id == CONSOLIDATED_TEMPLATE_ID

      raise Error, "#{template_name} points at template #{template_id.inspect}, not " \
                   "#{CONSOLIDATED_TEMPLATE_ID} (template 9658). The letter config changed; " \
                   'confirm which template carries the fee content before rendering.'
    end

    def resolve_log!(cca, log_id)
      log = CardmemberAgreementLog.find_by(id: log_id)
      raise Error, "no CardmemberAgreementLog #{log_id.inspect}" unless log

      unless log.credit_card_account_id == cca.id
        raise Error, "agreement log #{log.id} belongs to account #{log.credit_card_account_id}, " \
                     "not #{cca.id}"
      end

      # render_pdf returns the stored document when there is one, sending no request at all - so a
      # reused log yields a document with no fresh provenance and an unchanged version id.
      # `.present?` would raise: document_pdf is binary and blank? strips it as UTF-8.
      unless log.document_pdf.nil?
        raise Error, "agreement log #{log.id} already holds a rendered document (version " \
                     "#{log.template_version_id.inspect}). Renders are one per log: create a new " \
                     'csp_requested log from this one\'s template_variables and pass its id.'
      end

      log
    end

    # The issuance log is created with template_variables nil, and render_pdf on it renders
    # nothing (FINDINGS #27). generate_cardmember_agreement_inputs supplies them, but only for an
    # application approved with product.approve! - one approved through the dashboard dev tool has
    # no product decision and raises here instead.
    def ensure_template_variables!(cca, log)
      return if log.template_variables.present?

      inputs = cca.generate_cardmember_agreement_inputs
      raise Error, "generate_cardmember_agreement_inputs returned nothing for account #{cca.id}" if inputs.blank?

      log.update!(template_variables: inputs)
    rescue LocalCmaRender::Error
      raise
    rescue StandardError => e
      # The failure that actually happens here is a DataSourceBuildError about
      # annual_membership_fee_amount, and it says nothing about the agreement.
      raise Error, "cannot build agreement inputs for account #{cca.id}: #{e.class}: " \
                   "#{e.message}. An application approved through the dashboard dev tool has no " \
                   'product decision; approve with product.approve! instead (FINDINGS #27).'
    end

    def provenance_for(cca, log, strategy, template_name, template_id)
      probe = LocalRenderProvenance.last

      unless probe
        raise Error, 'the render sent no request to TemplateFlow, so it has no provenance. ' \
                     'Either the document came from the log rather than the wire, or ' \
                     'zzz_local_render_provenance.rb is not loaded - check the boot log for ' \
                     '[local] LocalRenderProvenance.'
      end

      raise Error, "nothing rendered: agreement log #{log.id} has no document_html" if log.document_html.blank?

      cross_check_provenance!(log, template_id, probe)

      {
        pricing_strategy:      strategy,
        credit_card_account_id: cca.id,
        agreement_log_id:      log.id,
        template_name:         template_name.to_s,
        template_id:           template_id,
        template_version_id:   log.template_version_id,
        all_version_uuids:     probe[:all_version_uuids],
        preview:               probe[:preview],
        allow_unapproved:      probe[:allow_unapproved],
        templateflow_host:     probe[:templateflow_host],
        rendered_at:           probe[:rendered_at],
        draft_render:          true,
      }
    end

    # The column and the wire must agree. A mismatch means the document on the log was not
    # produced by the render just made, which is the one way a stamped version can lie.
    def cross_check_provenance!(log, template_id, probe)
      if probe[:template_id] != template_id
        raise Error, "the render went to template #{probe[:template_id].inspect} but the letter " \
                     "config for this account says #{template_id.inspect}"
      end

      if probe[:template_version_id].blank?
        raise Error, 'TemplateFlow returned no template_version_uuid, so this document cannot be ' \
                     'attributed to a version (FINDINGS #22)'
      end

      return if log.template_version_id.to_s == probe[:template_version_id].to_s

      raise Error, "agreement log #{log.id} records version " \
                   "#{log.template_version_id.inspect} but the render used " \
                   "#{probe[:template_version_id].inspect}"
    end

    def write_evidence!(log, provenance, out_dir)
      FileUtils.mkdir_p(out_dir)
      base = "cma_#{provenance[:pricing_strategy]}_log#{log.id}"

      files = {
        html:       File.join(out_dir, "#{base}.html"),
        pdf:        File.join(out_dir, "#{base}.pdf"),
        provenance: File.join(out_dir, "#{base}.provenance.json"),
      }

      File.write(files[:html], log.document_html.to_s)
      File.binwrite(files[:pdf], log.document_pdf.to_s)
      provenance = provenance.merge(files: files)
      File.write(files[:provenance], JSON.pretty_generate(provenance))

      provenance
    end
  end
end
