# Deploy BidSphere to Vercel

This project uses Django 6, PostgreSQL in production, and Vercel's zero-configuration Django support. A successful deployment still requires environment variables and an external database; the ZIP cannot supply your provider credentials.

## 1. Import the project

Commit this folder to a Git repository and import that repository in Vercel. Leave the framework/build settings at their detected defaults unless Vercel reports a specific build error. Vercel supports Python 3.14; the repository pins it in `.python-version`.

## 2. Configure environment variables

Set these for every Vercel environment you intend to deploy:

```text
DJANGO_SECRET_KEY=<a unique, long random secret>
DJANGO_DEBUG=0
DATABASE_URL=<your persistent PostgreSQL connection URL>
```

Use a separate database for previews if practical. The app intentionally fails startup in production when its secret key or PostgreSQL URL is missing instead of silently using an insecure key or temporary SQLite database.

For a custom domain, set `DJANGO_PRIMARY_DOMAIN` to the hostname only, such as `bidsphere.example.com`, and add it to `DJANGO_ALLOWED_HOSTS` if you override that variable.

## 3. Apply database migrations

After setting the production environment variables and linking the local project with Vercel CLI, run:

```powershell
npx.cmd vercel@latest link
npx.cmd vercel@latest env run --environment production -- python manage.py migrate
```

The category migration seeds the default categories. Do **not** run `seed_demo --reset` against a production database: it deletes the documented demo accounts and all records attached to them. Demo seeding is blocked when `DEBUG=0` unless an explicit override is set for an isolated showcase environment.

If you need admin access, create a dedicated administrator with a strong unique password:

```powershell
npx.cmd vercel@latest env run --environment production -- python manage.py createsuperuser
```

## 4. Persistent image uploads

Vercel's local filesystem is not persistent storage for user-uploaded images. Configure an S3-compatible bucket (AWS S3, Cloudflare R2, or another compatible provider) and set:

```text
AWS_STORAGE_BUCKET_NAME=<bucket-name>
AWS_ACCESS_KEY_ID=<access-key>
AWS_SECRET_ACCESS_KEY=<secret-key>
AWS_S3_REGION_NAME=<region, if the provider uses one>
AWS_S3_ENDPOINT_URL=<provider endpoint, when required; omit for AWS S3>
AWS_S3_CUSTOM_DOMAIN=<public CDN/domain serving uploaded media, if configured>
AWS_S3_ADDRESSING_STYLE=auto
AWS_QUERYSTRING_AUTH=0
```

Keep credentials in Vercel environment variables, never in source control. Configure the bucket's policy/CORS for how you plan to serve public auction images. If no bucket is configured, local development uses `media/`; production uploads are not durable until object storage is configured.

## 5. Settle expired auctions

Normal traffic also synchronizes auction status, but relying on visits alone can delay settlement for inactive auctions. Run the included management command on a scheduler with access to the production environment:

```bash
python manage.py close_expired
```

Schedule it at a frequency your hosting plan supports. A bearer-token endpoint is also available at `/internal/cron/close-expired/` for a scheduler that can send `Authorization: Bearer <CRON_SECRET>`. Set `CRON_SECRET` in the deployment environment before using that endpoint. Configure the actual schedule in your hosting provider (some Vercel plans restrict cron frequency); this project intentionally does not assume a plan-specific schedule. The command and endpoint are safe to retry: already-ended auctions are not paid out a second time. Do not expose an unauthenticated URL that runs this operation.

## 6. Verification before making the site public

Run in an environment with dependencies installed and a configured test database:

```bash
python -m pip install -r requirements.txt
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
python manage.py audit_wallets
```

After deployment, test account registration/login, auction creation, bidding from two separate user accounts, outbidding, cancellation, final settlement, the admin site, and image upload/display. The included wallet audit verifies the balance ledger, but it does not replace PostgreSQL concurrency and deployment tests.

## 7. GitHub Actions CI/CD

The repository includes `.github/workflows/ci-cd.yml`. It runs on pull requests to `main`, pushes to `main`, and manual workflow dispatches.

### What the pipeline does

1. Starts a temporary PostgreSQL 16 service for CI.
2. Installs the project's Python dependencies.
3. Validates project structure/source syntax, runs `manage.py check`, and verifies there are no uncommitted model migrations.
4. Runs the Django automated tests against PostgreSQL.
5. Runs `pip-audit` to check dependencies for known published vulnerabilities.
6. After the checks pass, creates a Vercel Preview for same-repository pull requests and a Production deployment after a push to `main`.

### Configure GitHub deployment environments and secrets

In GitHub, open **Settings → Environments** and create both `preview` and `production`. Store the following as **environment-level secrets in each environment**, not as repository-level Actions secrets:

- `VERCEL_TOKEN` — a Vercel access token.
- `VERCEL_ORG_ID` — the Vercel team/account ID from the linked project's `.vercel/project.json`.
- `VERCEL_PROJECT_ID` — the Vercel project ID from that same file.

If you previously added these as repository-level secrets, remove those copies after adding the environment-level secrets. This prevents normal CI/test jobs from seeing deployment credentials.

For `preview`, configure a required reviewer in the Environment protection rules: a preview builds code from a pull request, so the deployment job should not receive credentials until a reviewer approves it. For `production`, use the `production` environment with protection/approval rules and protect the `main` branch. Never commit deployment credentials.

Configure Django runtime variables (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, `DATABASE_URL`, and media-storage credentials when used) in Vercel's Production environment. Configure separate Preview values and, preferably, a separate Preview database.

### Avoid duplicate or ungated deployments

This workflow deploys using the Vercel CLI only after CI succeeds. If Vercel's Git integration is also automatically deploying each push independently, disable that automatic deployment path for this project; otherwise a deployment might happen even when a GitHub Actions check fails. Keep deployment credentials only in GitHub Actions secrets and Vercel environment variables.

The workflow deploys from `main`. If your production branch has another name, update the `branches` list and the `refs/heads/main` condition in `.github/workflows/ci-cd.yml`.

Create a GitHub Environment named `production` under **Settings → Environments** if you want the production job to use environment protections or approval rules. This is recommended for a public project.

### Database migrations are intentionally separate

The workflow does not automatically run `migrate` against your live database. Review and apply migrations as a controlled release step using the instructions in section 3. This avoids an unreviewed code push silently changing production data. For zero-downtime releases, make schema changes backward-compatible across the old and new app versions.

### CI database TLS behavior

For deployed production/Vercel environments, BidSphere requires SSL for a configured database URL. In local development and GitHub CI with `DJANGO_DEBUG=1`, a local PostgreSQL service can connect without TLS. Do not enable debug mode in production.
