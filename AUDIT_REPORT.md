# BidSphere technical audit report

**Audit date:** 12 October 2026  
**Scope:** Python source, auction and wallet logic, Django views/forms/models/migrations by inspection, templates and route references, static JavaScript, Vercel configuration, GitHub Actions CI/CD workflow, environment-variable configuration, and repository/deployment docs.

## Executive result

This review found and corrected several code-level and cross-file issues. Static validation and isolated tests pass, but this environment could not install Django because package-index DNS resolution fails. Therefore, the Django ORM-backed test suite, migration checks, database checks, dependency audit, and a real Vercel build remain **unverified**. Do not interpret the static checks as proof of production readiness.

## Changes made in this audit build

- Fixed upcoming-auction countdown synchronization. The status API now returns a separate `start_remaining_seconds`, and browser polling uses the start time while an auction is upcoming and the end time after it becomes active. Ended and cancelled auctions stop counting down immediately.
- Preserved the last displayed auction price on cancellation rather than resetting the price to zero; cancellation still clears the leading bidder and sale-result fields and releases all active proxy reserves.
- Added a test that checks an upcoming auction's start countdown is distinct from its end countdown.
- Added a cross-auction wallet test to check that reservations across multiple auctions share the same available-credit balance.
- Added local `.env` loading through `python-dotenv`, with `override=False` so environment variables supplied by CI/Vercel take precedence.
- Scoped Vercel deployment secrets to GitHub `preview` and `production` Environments. The deployment guide now instructs maintainers to remove repository-level copies and require reviewer approval for preview deployments before pull-request code receives Vercel credentials.
- Removed unused imports in the views module.

The earlier project fixes are retained: proxy bids continue to reserve their maxima, visible price is kept monotonic during bidding, settlement is idempotent, expired auctions cannot be cancelled as if still live, the demo seeder creates ended lots by bidding before expiring them, watchlist state changes require POST, production requires explicit secret/database configuration, and uploaded media can use S3-compatible storage.

## Checks that passed in this environment

| Check | Result | Notes |
|---|---|---|
| `python validate_project.py` | PASS | 27 Python source files parsed; required files present |
| `python -m compileall` | PASS | Python files compile to bytecode |
| `node --check static/auction/js/app.js` | PASS | JavaScript syntax check |
| Parse `vercel.json` | PASS | Valid JSON |
| Parse `.github/workflows/ci-cd.yml` | PASS | YAML parses; GitHub's workflow semantics still need a GitHub Actions run |
| Template `{% url %}` references | PASS | All 20 distinct template URL names match route names |
| Isolated proxy-pricing scenarios | PASS | 6 scenarios: no bidders, first bid, runner-up price, leader max increase, leader switch, equal-max tie |
| Browser polling countdown simulation | PASS | Upcoming countdown remains tied to start time rather than auction end time |
| Archive integrity | PASS | Final ZIP is checked with `ZipFile.testzip()` after packaging |

## Checks that could not run

The following commands were attempted but stopped at startup because Django is not installed:

- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py test --verbosity 2`
- `python manage.py collectstatic --noinput --clear`
- `python manage.py audit_wallets`

Installing the project's requirements also failed because the environment could not resolve the Python package index (`Temporary failure in name resolution`). The repository currently contains **32 Django test methods**, but I cannot honestly report how many pass until those tests execute in a network-enabled environment against PostgreSQL.

Not performed here: live PostgreSQL migration and concurrency tests, `pip check`, `pip-audit`, Vercel CLI build/deploy, deployment smoke tests, real object-storage upload, or scheduled settlement run.

## Important remaining deployment requirements

1. **GitHub environments:** Create `preview` and `production` Environments, store `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` as environment-level secrets, remove repository-level copies, and set reviewer approval for previews and appropriate protection for production.
2. **Production variables:** Set a unique `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, and persistent PostgreSQL `DATABASE_URL` in Vercel.
3. **Uploaded media:** Configure and test S3-compatible storage before relying on long-term persistence of uploaded product/profile images. Local filesystem storage is not durable on Vercel.
4. **Scheduled settlement:** Configure a scheduler to run `python manage.py close_expired` or call `/internal/cron/close-expired/` with `Authorization: Bearer <CRON_SECRET>`.
5. **Runtime validation:** Let GitHub Actions run on a real repository. It is configured to run Django checks, migration-drift checks, PostgreSQL-backed tests, static collection, and `pip-audit` before deployment. Resolve any failures before releasing.

## Dependency version note

The project stays on Django 6.0.9. The official Django security announcement dated 6 October 2026 lists 6.0.9 as the security-patched 6.0 release, while 6.1.2 is also available on the newer feature branch. I did not upgrade the application branch without being able to run its compatibility test suite. Django 6.0 supports Python 3.14, and Vercel documents support for Python 3.14.

References:
- https://www.djangoproject.com/weblog/2026/oct/06/security-releases/
- https://docs.djangoproject.com/en/6.0/releases/6.0/
- https://vercel.com/docs/functions/runtimes/python

## User-run Django checks and test follow-up

On 12 October 2026, the user ran the project on Windows after installing the requirements. Their output confirms:

- `python manage.py check`: PASS (no issues).
- `python manage.py makemigrations --check --dry-run`: PASS (no changes detected).
- 32 Django tests executed: 31 passed and one errored before running the demo-seeder assertions. The cause was the expected production safety guard (`DEBUG=False`) rejecting `seed_demo`; the test had assumed debug mode and was therefore environment-dependent.

The follow-up build fixes the test rather than weakening the command's production guard: the seeder-success test overrides `DEBUG=True` only for that isolated test, and a dedicated test verifies seeding is refused under `DEBUG=False` without the explicit opt-in. This raises the suite to 33 tests. **The suite has not yet been rerun against this follow-up patch**, so its result must be confirmed with `python manage.py test --verbosity 2`.

## Final confidence statement

The user-provided runtime output confirms Django's system checks and migration-drift check pass on their machine. The only reported test error has been addressed at the test-fixture level, with additional coverage for the production guard, but the new 33-test suite still needs a rerun. The application is **not certified as fully tested or production-ready** until that rerun, PostgreSQL concurrency/integration checks, dependency auditing, and a real Vercel deployment are verified.
