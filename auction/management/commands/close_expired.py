from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from auction.models import Auction
from auction.services import close_auction


class Command(BaseCommand):
    help = "Settle expired BidSphere auctions."

    def handle(self, *args, **options):
        ids = list(
            Auction.objects.filter(
                status__in=[Auction.Status.UPCOMING, Auction.Status.ACTIVE],
                end_time__lte=timezone.now(),
            ).values_list("id", flat=True)
        )
        closed = 0
        failures = []
        for auction_id in ids:
            try:
                result = close_auction(auction_id)
                if result.status == Auction.Status.ENDED:
                    closed += 1
            except Exception as exc:
                failures.append(auction_id)
                self.stderr.write(f"Could not close auction {auction_id}: {exc}")
        summary = f"Checked {len(ids)} expired auctions; settled {closed}; failed {len(failures)}."
        if failures:
            raise CommandError(summary + f" Failed auction IDs: {', '.join(map(str, failures))}")
        self.stdout.write(self.style.SUCCESS(summary))
