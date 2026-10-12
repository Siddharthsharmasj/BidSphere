# Changelog

## 2026-09-29 — clean rebuild

- Removed Channels/Daphne from the deployment-critical path.
- Switched to standard Django WSGI for simpler local + Vercel execution.
- Made local development default to HTTP and `DJANGO_DEBUG=1`.
- Added robust PostgreSQL environment-variable discovery for Vercel Marketplace integrations.
- Implemented atomic maximum/proxy bidding.
- Implemented wallet reservations, releases, final payment and seller payout.
- Added signed wallet ledger and audit command.
- Added anti-sniping extensions.
- Added lazy auction expiry settlement through normal page/API traffic plus a management command for scheduled cleanup.
- Added demo marketplace and accounting tests.


## 2026-10-12 — reliability and deployment hardening

- Fixed maximum/proxy bidding so all active bidder maxima remain active and reserved until settlement/cancellation.
- Prevented displayed prices from decreasing when a leader increases their maximum.
- Added regression coverage for competing proxies, tied maxima, monotonic price, wallet capacity, settlement, and protected settlement triggering.
- Required a production secret key and PostgreSQL URL; added Vercel/custom-domain host and CSRF configuration.
- Registered the root-level `static/` folder so existing CSS and JavaScript are collected.
- Added optional S3-compatible image storage settings for durable deployed uploads.
- Restricted watchlist changes to POST and validated notification redirect targets.
- Blocked demo seed/reset with known credentials when debug mode is disabled.
- Added an optional bearer-token-protected settlement endpoint and expanded the expiry command to include stale upcoming auctions.
- Updated deployment documentation to avoid destructive demo reset in production.

## CI/CD addition (2026-10-12)

- Added `.github/workflows/ci-cd.yml` with Python/Django configuration checks, migration drift detection, PostgreSQL-backed automated tests, and dependency vulnerability auditing.
- Added gated Vercel Preview deployments for same-repository pull requests and Production deployments on pushes to `main`.
- Documented required GitHub Actions secrets, Vercel environment setup, and controlled production migrations.
- Adjusted database TLS enforcement so deployed environments require TLS while local/CI PostgreSQL can run without TLS when `DJANGO_DEBUG=1`.

## Audit fixes (October 12, 2026)
- Bumped Django to 6.0.9 to include the October 6, 2026 security fixes.
- Prevented cancelling an auction after its deadline, even when its persisted status has not yet been lazily synchronized.
- Fixed the auction-list API to synchronize expired/upcoming auctions before querying results, avoiding stale statuses and prices.
- Added regression tests for post-deadline cancellation and API status synchronization.
- Made wallet, bid-history, and proxy-bid admin records read-only to prevent manual edits from desynchronizing reservations and ledger balances.
- Clarified that bid-history values represent the public price after the maximum was submitted, not the bidder's private maximum.
- Corrected expired-auction command reporting when an auction is extended concurrently.
- Prevented admin deletion/edit paths that could erase active reserves or desynchronize wallet ledger values.
- Expanded `audit_wallets` to reconcile the ledger against current available credits, outstanding proxy reserves, and balance-after snapshots.
- Settlement now recalculates from active proxy maxima and caps the final charge at the winner's reserved maximum if stored auction price data is inconsistent.

## Audit follow-up

- Fixed upcoming-auction countdown synchronization: the status API now returns start and end countdowns separately, and the browser uses the correct target during polling. Terminal auction statuses stop the countdown immediately.
- Local `.env` files are now loaded with `python-dotenv` without overriding environment values supplied by CI/Vercel.
- Vercel deployment credentials are expected to be environment-scoped; preview deployment is gated by a GitHub `preview` Environment so reviewers can approve untrusted pull-request builds before the Vercel token is exposed.
- Added a regression test for distinct start/end countdown values on upcoming auctions.
- Audit run limitations are documented in `AUDIT_REPORT.md`; Django runtime tests could not be executed in the current environment because package-index DNS/network access is unavailable.



## Test follow-up (October 12, 2026)

- Made the demo-seeder regression test deterministic by overriding `DEBUG=True` only within the isolated test; this avoids an environment `.env` value such as `DJANGO_DEBUG=0` blocking a local test.
- Added a separate test proving demo seeding remains blocked when `DEBUG=False` and `ALLOW_DEMO_SEED_IN_PRODUCTION` is not explicitly enabled. The production safety guard remains unchanged.
