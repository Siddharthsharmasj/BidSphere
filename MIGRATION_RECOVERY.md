# Migration recovery

For a fresh checkout, use:

```powershell
python manage.py migrate
```

The initial migration includes explicit names for every database index because Django 6.0 requires named indexes in migration state.

If a previous copy of BidSphere has a partially applied initial migration or an old SQLite schema, use a new checkout/folder rather than trying to mix old migration files with this rebuild.


## Upgrading an existing database from the earlier proxy-bid behavior

Earlier builds could release and deactivate losing proxy bids as soon as a new
leader appeared. The corrected behavior keeps every active bidder's maximum
reserved until settlement/cancellation. Do not blindly reactivate old inactive
proxy rows: their reserve may have been released and the bidder may have spent
those credits elsewhere. Before upgrading a database that contains live
auctions from an older build, run `python manage.py audit_wallets`, inspect the
active auctions' proxy rows, and deliberately settle/cancel/reopen affected
auctions or reconcile them using a reviewed data-recovery plan. A fresh database
or a preview clone is the safest first verification environment.
