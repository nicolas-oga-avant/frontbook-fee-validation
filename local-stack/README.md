# Local stack snapshot

Copies of the untracked override files that make the local basic + CCAPI + CRM stack work.
They live in the repos (and only in `.git/info/exclude`), so a `git clean -xfd` in any of those
checkouts deletes them. These are the backups.

```bash
./restore.sh          # put them back and re-exclude them (idempotent)
./restore.sh --up     # ...and start all three stacks, including the CRM client bundle
```

| File here | Restore to |
| --- | --- |
| `avant-basic.docker-compose.override.yml` | `avant-basic/docker-compose.override.yml` |
| `zzz_local_transunion_mock.rb` | `avant-basic/config/initializers/` |
| `zzz_local_cma_stub.rb` | `avant-basic/config/initializers/` |
| `zzz_local_consolidated_cma.rb` | `avant-basic/config/initializers/` |
| `credit-card-api.compose.override.yml` | `credit-card-api/compose.override.yml` |
| `crm.docker-compose.override.yml` | `crm/docker-compose.override.yml` |

`restore.sh` handles the `.git/info/exclude` entries itself and prints a check that nothing became
git-visible. The checkouts are shared with other agent sessions, so never commit these and never
switch branches to accommodate them.

## What each one is for

| File | Why it exists |
| --- | --- |
| `avant-basic.docker-compose.override.yml` | points basic at local CCAPI; sets `CONFETTI_ENV`, `ENABLE_MOCK_SERVICES`, `MOCK_TRANSUNION` |
| `zzz_local_transunion_mock.rb` | registers `FakeTransunion`, without which every local application declines (FINDINGS #14) |
| `zzz_local_cma_stub.rb` | `LocalCmaStub` - fills the Fiserv-only fields so a freshly issued card can render a CMA (FINDINGS #15) |
| `zzz_local_consolidated_cma.rb` | lets the `needs_consolidated_cma` tag past the Optimizely guard, so Runs render the consolidated CMA - the only template carrying the fee variables (FINDINGS #21) |
| `credit-card-api.compose.override.yml` | live minio image, local basic, dev FDR gateway, and `CONFETTI_URL` (not `_URI`) |
| `crm.docker-compose.override.yml` | CSP against local basic, password login instead of Okta, host port 4000 |

The `zzz` prefix is load-bearing for `zzz_local_transunion_mock.rb`: it must run after
`mock_services.rb`, which is what enables WebMock. `zzz_local_cma_stub.rb` only defines a module,
and `zzz_local_consolidated_cma.rb` defers its prepend to `to_prepare`, so neither depends on load
order - they keep the prefix for consistency.
