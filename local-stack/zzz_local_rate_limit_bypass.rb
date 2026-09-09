# UNTRACKED local-only initializer for the frontbook fee launch validation. See FINDINGS #39.
#
# Why this exists
# ----------------
# Customer#check_and_track_application_rate_limit! (avant-basic/app/models/customer.rb:759) raises
# once an IP has created CustomerApplication::MAXIMUM_ALLOWED_PER_DAY_FROM_SAME_IP (10)
# applications in a day, tracked in Redis via Avant::CustomerFraudRingTracker. It exempts internal
# IPs (Util::WhiteList.internal_ip?, lib/avant/util/white_list.rb:5), but that list is a hardcoded
# handful of office/VPN/AWS addresses - it does not cover a Docker bridge network, so the
# container's own gateway IP counts as external.
#
# A validation session that makes each Run cheap enough to retry casually (scripts/
# run_apply_standalone.py, scripts/run_validation.py) walks the apply flow far more than 10 times
# a day without anyone deliberately doing anything wrong. Once tripped, every subsequent apply URL
# 500s, and apply_driver.py - which only polls the SPA's hash, never the HTTP status - reports it
# as an ordinary SubmitFailed that looks identical to FINDINGS #38's transient cold-Chrome timeout.
# The two are not the same: this one repeats on every attempt until the Redis key expires (up to
# 24h) or is cleared, while #38 self-resolves on retry.
#
# What this changes
# ------------------
# Prepends onto Customer to skip the rate-limit check entirely under Rails.env.development? -
# nothing for this validation stack to trip, ever. Scoped to development on purpose: this must
# never affect a deployed environment, and the guard is the same one every other zzz_local_*.rb
# initializer in this repo uses.
module LocalRateLimitBypass
  module Probe
    def check_and_track_application_rate_limit!(ip_address)
      return if Rails.env.development?

      super
    end
  end
end

if Rails.env.development?
  Rails.application.config.to_prepare do
    unless Customer.included_modules.include?(LocalRateLimitBypass::Probe)
      Customer.prepend(LocalRateLimitBypass::Probe)
    end
  end

  Rails.logger.info(
    '[local] LocalRateLimitBypass active - application-creation rate limiting disabled for this '\
    'validation stack (FINDINGS #39)'
  )
end
