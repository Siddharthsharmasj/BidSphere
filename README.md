# BidSphere — Django Virtual-Credit Auction Simulator

BidSphere is a full Django auction marketplace built around **virtual credits**. It is intentionally a simulator for learning and portfolio use; it does not process real-money payments.

## What is implemented

- User registration, login/logout and profiles (5 MB avatar upload cap)
- Seller auction publishing with optional images (8 MB upload cap)
- Live, upcoming, ended and cancelled auction states
- Search, categories, status filters and sorting
- Maximum/proxy bidding
- Atomic wallet reservation and release logic
- Reserve release on auction settlement or cancellation
- Final settlement: winner pays final visible price, unused maximum is released, seller receives proceeds
- Wallet transaction ledger with balance-after snapshots
- Anti-sniping extension when a valid bid lands near the end
- Watchlist and notifications
- Bid history and auction statistics
- Seller dashboard and analytics
- Reporting + Django admin moderation
- JSON status/bid APIs for near-real-time browser polling
- Demo marketplace data (intended for local/isolated preview use)
- Optional S3-compatible persistent image storage
- Wallet audit command that checks available balances, active reservations, and ledger snapshots
- Expired-auction settlement command
- Automated accounting tests
- SQLite for local development; persistent PostgreSQL is required on Vercel/production

## Important accounting model

`Profile.available_credits` is spendable balance. Each active bidder's maximum is held separately on `ProxyBid.reserved_amount` until the auction ends or is cancelled.

`wallet_total = available_credits + active reserved credits`

All active proxy bids remain eligible to become the leader. The visible price is calculated from the leading maximum and runner-up, is capped at the leading maximum, and never decreases. At settlement, all reserves are released, the winner's final price is charged, and the seller receives the proceeds.

## Windows local setup

The easiest option on your machine is the included batch file:

```text
setup_and_run.bat
```

Or run manually:

```powershell
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo --reset
python manage.py runserver
```

PowerShell execution-policy fix, only for the current window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Open:

```text
http://127.0.0.1:8000/
```

Do **not** type `https://127.0.0.1:8000/` for local development.

## Demo accounts (local development only)

The seed command creates:

```text
demo_seller
demo_seller_2
demo_bidder_1
demo_bidder_2
demo_bidder_3
```

Password:

```text
DemoBidSphere123!
```

Use two browser profiles/incognito windows to test two different bidders.

## Useful commands

```powershell
python manage.py seed_demo --reset
python manage.py close_expired
python manage.py audit_wallets
python manage.py test
python manage.py check
```

## Vercel deployment

Vercel's current zero-configuration Django support can deploy a Django application without putting the app behind an `/api` folder. PostgreSQL should be used for production. The project accepts these connection variable names, in priority order:

```text
DATABASE_URL
DATABASE_POSTGRES_URL
DATABASE_POSTGRES_URL_NON_POOLING
DATABASE_POSTGRES_URL_UNPOOLED
```

It will also discover a Vercel Marketplace database URL that ends with `_DATABASE_URL` or `_POSTGRES_URL`.

Set in Vercel:

```text
DJANGO_SECRET_KEY=<strong-random-secret>
DJANGO_DEBUG=0
```

Connect Neon/Postgres through Vercel Storage/Marketplace and let its secret environment variables remain managed by Vercel.

After the project is linked locally:

```powershell
npx.cmd vercel@latest link
npx.cmd vercel@latest env pull .env.vercel
npx.cmd vercel@latest env run --environment production -- python manage.py migrate
# Do not seed known demo credentials in the production database.
```

### Production behavior

- Local: HTTP, SQLite, debug on by default
- Vercel: HTTPS security enabled when `DJANGO_DEBUG=0`; a PostgreSQL URL and strong secret key are required
- Live auction cards use short polling requests, so the public app does not depend on a long-running ASGI/WebSocket server
- For automatic expiry processing without a visitor opening the auction, schedule `python manage.py close_expired` externally or use a suitable Vercel scheduled function for your plan

## Why this version avoids the earlier deployment crash

The deployment-critical app uses Django's standard WSGI entry point and does not import auction ORM code from an ASGI router at startup. This removes the `AppRegistryNotReady` startup path that occurred previously.

## Project structure

```text
BidSphere/
├── auction/
│   ├── management/commands/
│   ├── migrations/
│   ├── models.py
│   ├── services.py
│   ├── views.py
│   ├── forms.py
│   └── tests.py
├── bidsphere/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── static/auction/
├── templates/auction/
├── manage.py
├── requirements.txt
├── vercel.json
└── setup_and_run.bat
```


## Deployment safety notes

- CSS and JavaScript are collected from the project-level `static/` directory.
- Production settings require a unique `DJANGO_SECRET_KEY` and persistent PostgreSQL database URL.
- Configure object storage before allowing persistent image uploads on Vercel.
- Run `python manage.py close_expired` on a schedule; an optional bearer-token endpoint is available for a hosting scheduler when `CRON_SECRET` is configured.

## Continuous integration and deployment

A GitHub Actions workflow is included at `.github/workflows/ci-cd.yml`. It checks Python/Django configuration, migration drift, runs the automated suite against PostgreSQL, audits dependencies, and deploys Vercel Preview/Production only after the checks pass. Configure `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` as environment-level secrets under protected GitHub `preview` and `production` Environments (not repository-level secrets); require reviewer approval for preview deployments. See `DEPLOY_TO_VERCEL.md` for setup and production safety notes.
