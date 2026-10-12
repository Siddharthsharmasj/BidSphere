from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

from auction.models import Auction, Profile, ProxyBid, WalletTransaction

User = get_user_model()


class Command(BaseCommand):
    help = "Check wallet ledger balances and active reserve totals."

    def handle(self, *args, **options):
        failures = 0

        # User-created profiles normally arrive through a signal. Detect old,
        # imported, or manually damaged accounts where that invariant failed.
        missing_profiles = User.objects.filter(profile__isnull=True).values_list("username", flat=True)
        for username in missing_profiles.iterator():
            failures += 1
            self.stdout.write(self.style.ERROR(f"FAIL {username}: user has no wallet profile"))

        # The ledger reconciliation below catches mismatched wallet movements;
        # these row-level invariants also catch active proxies without full
        # funding and inactive proxies that still claim to hold credits.
        for proxy in ProxyBid.objects.select_related("auction", "bidder").iterator():
            issue = None
            if proxy.active and proxy.reserved_amount != proxy.max_amount:
                issue = f"active proxy reserve={proxy.reserved_amount:.2f}, maximum={proxy.max_amount:.2f}"
            elif not proxy.active and proxy.reserved_amount != Decimal("0.00"):
                issue = f"inactive proxy still reserves {proxy.reserved_amount:.2f}"
            elif proxy.active and proxy.auction.status in {Auction.Status.ENDED, Auction.Status.CANCELLED}:
                issue = f"closed auction {proxy.auction_id} still has an active proxy"
            if issue:
                failures += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"FAIL {proxy.bidder.username} / auction {proxy.auction_id}: {issue}"
                    )
                )

        for profile in Profile.objects.select_related("user"):
            transactions = profile.user.wallet_transactions
            summary = transactions.aggregate(
                total=Sum("amount"),
                reserve_net=Sum(
                    "amount",
                    filter=Q(kind__in=[WalletTransaction.Kind.RESERVE, WalletTransaction.Kind.RELEASE]),
                ),
            )
            ledger_total = summary["total"] or Decimal("0.00")
            expected_available = ledger_total
            actual_available = profile.available_credits
            reserved = profile.reserved_credits
            reserve_net = summary["reserve_net"] or Decimal("0.00")
            expected_reserved = -reserve_net
            issues = []
            if (expected_available - actual_available).quantize(Decimal("0.01")) != Decimal("0.00"):
                issues.append(f"ledger available={expected_available:.2f} actual available={actual_available:.2f}")
            if expected_reserved < 0 or (expected_reserved - reserved).quantize(Decimal("0.01")) != Decimal("0.00"):
                issues.append(f"ledger reserved={expected_reserved:.2f} active proxies reserved={reserved:.2f}")

            # Verify balance-after snapshots against the chronological ledger.
            running_balance = Decimal("0.00")
            for tx in transactions.order_by("created_at", "pk").only("amount", "balance_after"):
                running_balance += tx.amount
                if (running_balance - tx.balance_after).quantize(Decimal("0.01")) != Decimal("0.00"):
                    issues.append(f"incorrect balance_after snapshot at transaction {tx.pk}")
                    break

            if issues:
                failures += 1
                self.stdout.write(self.style.ERROR(f"FAIL {profile.user.username}: " + "; ".join(issues)))
            else:
                self.stdout.write(
                    f"OK {profile.user.username}: available={actual_available:.2f} reserved={reserved:.2f} total={profile.wallet_total:.2f}"
                )
        if failures:
            raise SystemExit(f"Wallet audit failed for {failures} profile(s).")
        self.stdout.write(self.style.SUCCESS("Wallet audit passed."))
