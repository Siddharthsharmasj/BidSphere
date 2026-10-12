# START HERE — BidSphere

BidSphere is a Django auction simulator with virtual credits, maximum proxy bids, watchlists, notifications, and seller analytics.

## Local Windows setup

Open PowerShell in this folder (the one containing `manage.py`):

```powershell
py -3.14 -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py check
python manage.py migrate
python manage.py seed_demo --reset
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser. Local development defaults to HTTP; do not use HTTPS locally.

## Demo sign-ins (local development only)

```text
demo_bidder_1 / DemoBidSphere123!
demo_bidder_2 / DemoBidSphere123!
```

These known demo credentials are for local testing only. The seed command refuses to run with production settings unless explicitly overridden for an isolated showcase environment.

## Proxy bidding behavior

Each active participant retains their maximum proxy bid and reserves that amount from their virtual-credit wallet. The visible price is computed from the highest maximum and the runner-up, never decreases, and can never exceed the leader's maximum. When an auction ends or is cancelled, every reservation is released and a winner's final price is charged at most once.

## Vercel

Read `DEPLOY_TO_VERCEL.md` before deploying. Production requires `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=0`, and a persistent PostgreSQL `DATABASE_URL`. To persist image uploads, configure S3-compatible object storage. Run migrations after setting the production environment variables; do not reset demo data in the production database.
