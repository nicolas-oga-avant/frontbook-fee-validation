# UNTRACKED local-only initializer for the frontbook fee launch validation. See
# TESTING_BLOCKERS.md item 3 and FINDINGS #35.
#
# Why this exists
# ----------------
# The account-opening Schumer box (a section of the `personal_continued` apply stage) is served
# by CAF's React micro-frontend, pinned by URL in `version_config.yml`'s `react_index_url` -
# `us_avantcredit_credit_card/v/6.1` currently points at `11.4.0`, which predates CSRV-5843's fix
# for the two hardcoded launch rows (FINDINGS #35). CSRV-5844, the ticket that would bump this
# value in the repo, is blocked on CAF's own prod-deploy workflow - an operational lag on another
# team's schedule, not a policy embargo (TESTING_BLOCKERS.md item 3).
#
# CAF's "Dev deploy" workflow runs on every pull_request event and publishes a preview build to
# CloudFront's dev distribution keyed by PR number. PR #168 (CSRV-5843) is confirmed live there,
# so this is a pre-deploy path, not a workaround: it is the only way to get a real assertion out
# of this surface before CSRV-5844 lands.
#
# What this changes
# ------------------
# Prepends onto CustomerApplicationEngine::Core::Config's singleton class and overrides
# load_version_config so that, for exactly this one version's config file, the parsed
# react_index_url is replaced with the CAF preview bundle. Never edits the tracked YAML on disk
# (AGENTS.md hard rule 4 - the checkouts are shared, and a modified tracked file cannot be hidden
# from `git status` by `.git/info/exclude`, unlike the untracked files the other overrides add).
#
# Config.for defaults flush: true in Rails.env.development? (config.rb:18), which nils the class
# ivar caches before every call - so this re-applies fresh on every request with no server
# restart needed. ApplyController separately caches the fetched HTML forever per URL
# (@@cached_react_html, apply_controller.rb), but that is keyed by the URL string itself, so
# pointing at a different URL is a cache miss, never stale content.
#
# Caveat, not this file's job: the preview bundle is an ephemeral CI artifact on the dev
# distribution with no retention guarantee, owned by another team's pipeline. Assert it 200s at
# the start of every Run (scripts/apply_harness.py, assert_caf_preview_bundle_live) rather than
# assuming it persists - a 404 there is a halt-and-report (AGENTS.md: assume silence means
# failure), not a silent fall-back to the pinned prod bundle this file replaces.
module LocalCafPreviewBundle
  PREVIEW_BUNDLE_URL = 'https://d1gm0t5fpu3i9c.cloudfront.net/micro_frontends/168/index.html'.freeze

  # config/customer_application/us_avantcredit_credit_card/v/6.1 - the only version_config this
  # touches. A suffix match on the path Config.rb builds internally, not a full path, so it does
  # not care where the checkout root is.
  TARGET_PATH_SUFFIX = File.join('us_avantcredit_credit_card', 'v', '6.1')

  def load_version_config(path)
    config = super
    return config unless path.to_s.end_with?(LocalCafPreviewBundle::TARGET_PATH_SUFFIX)
    return config unless config['apply'].is_a?(Hash)

    config['apply']['react_index_url'] = LocalCafPreviewBundle::PREVIEW_BUNDLE_URL
    config
  end
end

if Rails.env.development?
  Rails.application.config.to_prepare do
    klass = CustomerApplicationEngine::Core::Config
    unless klass.singleton_class.included_modules.include?(LocalCafPreviewBundle)
      klass.singleton_class.prepend(LocalCafPreviewBundle)
    end
  end

  Rails.logger.info(
    '[local] LocalCafPreviewBundle active - us_avantcredit_credit_card v6.1 react_index_url ' \
    "points at #{LocalCafPreviewBundle::PREVIEW_BUNDLE_URL} (CSRV-5843 pre-deploy path)"
  )
end
