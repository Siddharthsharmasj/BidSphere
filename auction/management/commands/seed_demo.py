from datetime import timedelta
from decimal import Decimal

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from auction.models import Auction, Category
from auction.services import close_auction, place_max_bid

User = get_user_model()


class Command(BaseCommand):
    help = "Create a realistic BidSphere demo marketplace with virtual credits."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the demo users and auctions first.")

    def handle(self, *args, **options):
        if not settings.DEBUG and os.environ.get("ALLOW_DEMO_SEED_IN_PRODUCTION") != "1":
            raise CommandError(
                "Demo seeding is disabled when DEBUG is off because it creates publicly documented "
                "demo credentials. Seed locally or explicitly set ALLOW_DEMO_SEED_IN_PRODUCTION=1 "
                "only in an isolated demo environment."
            )

        demo_names = [
            "demo_seller", "demo_seller_2", "demo_bidder_1", "demo_bidder_2", "demo_bidder_3"
        ]
        if options["reset"]:
            # Demo reset must never delete the reference categories.
            # User deletion cascades to the demo auctions, so removing the demo
            # users is enough to clear the demo marketplace.
            User.objects.filter(username__in=demo_names).delete()

        category_data = [
            ("Electronics", "electronics"),
            ("Vehicles", "vehicles"),
            ("Fashion", "fashion"),
            ("Collectibles", "collectibles"),
            ("Art", "art"),
            ("Home & Garden", "home-garden"),
            ("Books", "books"),
            ("Sports", "sports"),
            ("Music", "music"),
            ("Other", "other"),
        ]
        # Always ensure categories exist. This makes --reset safe even when
        # categories were removed by an older seed command or database state.
        for name, slug in category_data:
            Category.objects.get_or_create(slug=slug, defaults={"name": name})
        categories = {c.slug: c for c in Category.objects.all()}
        now = timezone.now()
        users = {}
        for username in demo_names:
            user, created = User.objects.get_or_create(username=username, defaults={"email": f"{username}@example.com"})
            if created:
                user.set_password("DemoBidSphere123!")
                user.save(update_fields=["password"])
            profile = user.profile
            if options["reset"] or created:
                profile.available_credits = Decimal("100000.00")
                profile.save(update_fields=["available_credits"])
                # Remove all non-initial ledger entries on a reset/create refresh.
                user.wallet_transactions.exclude(kind="initial").delete()
            users[username] = user

        product_data = [
            ("Sony WH-1000XM5 Headphones", "Flagship wireless noise-cancelling headphones for the demo marketplace.", "electronics", Decimal("8500"), Decimal("250"), now - timedelta(hours=1), now + timedelta(hours=4), "active"),
            ("Keychron Q1 Mechanical Keyboard", "Premium aluminum mechanical keyboard, hot-swappable, excellent condition.", "electronics", Decimal("7000"), Decimal("200"), now - timedelta(hours=2), now + timedelta(minutes=12), "active"),
            ("Mirrorless Camera Starter Kit", "Camera body plus standard zoom lens and accessories.", "electronics", Decimal("42000"), Decimal("1000"), now - timedelta(minutes=30), now + timedelta(hours=6), "active"),
            ("Premium Leather Backpack", "Minimal professional leather backpack with laptop compartment.", "fashion", Decimal("4800"), Decimal("150"), now + timedelta(hours=1), now + timedelta(hours=8), "upcoming"),
            ("Vintage Film Camera Collection", "A small curated collection of classic film cameras.", "collectibles", Decimal("12000"), Decimal("500"), now + timedelta(hours=3), now + timedelta(days=1), "upcoming"),
            ("Programming Books Bundle", "Backend, databases, system design and Python reference books.", "books", Decimal("2200"), Decimal("100"), now + timedelta(hours=2), now + timedelta(hours=10), "upcoming"),
            ("27-inch 144Hz Gaming Monitor", "27-inch QHD high-refresh-rate display.", "electronics", Decimal("18500"), Decimal("500"), now - timedelta(days=2), now - timedelta(days=1), "ended"),
            ("Studio Condenser Microphone", "USB/XLR studio microphone for recording and streaming.", "music", Decimal("6500"), Decimal("250"), now - timedelta(days=2), now - timedelta(days=1), "ended"),
            ("Carbon-Fiber Badminton Racket", "Lightweight performance racket with carry case.", "sports", Decimal("3200"), Decimal("100"), now - timedelta(days=1), now - timedelta(hours=3), "ended"),
        ]

        sellers = [users["demo_seller"], users["demo_seller_2"]]
        created_auctions = []
        for idx, (title, description, slug, start_price, increment, start, end, target_status) in enumerate(product_data):
            seller = sellers[idx % 2]
            auction = Auction.objects.create(
                seller=seller,
                category=categories[slug],
                title=title,
                description=description,
                starting_price=start_price,
                minimum_increment=increment,
                start_time=start,
                # Ended demo lots must remain bid-able during seeding, then are
                # moved into the past and settled below. Trying to bid on a lot
                # whose end_time is already past correctly rejects the bid.
                end_time=(now + timedelta(minutes=15)) if target_status == "ended" else end,
                status=Auction.Status.UPCOMING if start > now else Auction.Status.ACTIVE,
                current_price=Decimal("0.00"),
            )
            created_auctions.append((auction, target_status))

        active = [a for a, s in created_auctions if s == "active"]
        bidders = [users["demo_bidder_1"], users["demo_bidder_2"], users["demo_bidder_3"]]
        bid_plans = [
            [(bidders[0], Decimal("14000")), (bidders[1], Decimal("12000")), (bidders[2], Decimal("16000"))],
            [(bidders[1], Decimal("12000")), (bidders[2], Decimal("9800"))],
            [(bidders[2], Decimal("52000")), (bidders[0], Decimal("50000"))],
        ]
        for auction, plan in zip(active, bid_plans):
            for bidder, amount in plan:
                try:
                    place_max_bid(auction.pk, bidder, amount)
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"Skipping demo bid on {auction.title}: {exc}"))

        ended = [(a, s) for a, s in created_auctions if s == "ended"]
        for i, (auction, _) in enumerate(ended):
            try:
                place_max_bid(auction.pk, bidders[i % len(bidders)], auction.starting_price + auction.minimum_increment * 4)
                auction.refresh_from_db()
                auction.end_time = now - timedelta(minutes=5)
                auction.save(update_fields=["end_time", "updated_at"])
                close_auction(auction.pk)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Could not settle demo ended auction {auction.title}: {exc}"))

        self.stdout.write(self.style.SUCCESS("Demo marketplace seeded successfully."))
        self.stdout.write("Demo password: DemoBidSphere123!")
