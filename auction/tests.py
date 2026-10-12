from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from io import StringIO

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from .models import Auction, Category, Notification, ProxyBid, WalletTransaction
from .services import AuctionError, cancel_auction, close_auction, place_max_bid


class AuctionAccountingTests(TestCase):
    def setUp(self):
        self.category, _ = Category.objects.get_or_create(
            slug="electronics", defaults={"name": "Electronics"}
        )
        self.seller = User.objects.create_user("seller", password="Password123!")
        self.alice = User.objects.create_user("alice", password="Password123!")
        self.bob = User.objects.create_user("bob", password="Password123!")

    def make_auction(self, *, minutes=30):
        now = timezone.now()
        return Auction.objects.create(
            seller=self.seller,
            category=self.category,
            title="Test item",
            description="Testing",
            starting_price=Decimal("1000.00"),
            minimum_increment=Decimal("100.00"),
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(minutes=minutes),
            status=Auction.Status.ACTIVE,
        )

    def test_new_bid_reserves_maximum(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.available_credits, Decimal("95000.00"))
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("5000.00"))
        self.assertEqual(auction.__class__.objects.get(pk=auction.pk).current_price, Decimal("1000.00"))

    def test_proxy_bidding_sets_visible_price_from_runner_up(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("3000"))
        auction.refresh_from_db()
        self.assertEqual(auction.current_bidder_id, self.alice.id)
        self.assertEqual(auction.current_price, Decimal("3100.00"))
        self.bob.profile.refresh_from_db()
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.available_credits, Decimal("95000.00"))
        self.assertEqual(self.bob.profile.available_credits, Decimal("97000.00"))
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("5000.00"))
        self.assertEqual(self.bob.profile.reserved_credits, Decimal("3000.00"))
        self.assertEqual(ProxyBid.objects.filter(auction=auction, active=True).count(), 2)

    def test_outbid_retains_both_proxy_reservations(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("7000"))
        auction.refresh_from_db()
        self.assertEqual(auction.current_bidder_id, self.bob.id)
        self.alice.profile.refresh_from_db()
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.available_credits, Decimal("95000.00"))
        self.assertEqual(self.bob.profile.available_credits, Decimal("93000.00"))
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("5000.00"))
        self.assertEqual(self.bob.profile.reserved_credits, Decimal("7000.00"))
        self.assertEqual(auction.current_price, Decimal("5100.00"))
        self.assertEqual(ProxyBid.objects.filter(auction=auction, active=True).count(), 2)

    def test_settlement_refunds_unused_max_and_pays_seller(self):
        auction = self.make_auction(minutes=1)
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("3000"))
        auction.end_time = timezone.now() - timedelta(seconds=1)
        auction.save(update_fields=["end_time", "updated_at"])
        close_auction(auction.id)
        auction.refresh_from_db()
        self.alice.profile.refresh_from_db()
        self.bob.profile.refresh_from_db()
        self.seller.profile.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ENDED)
        self.assertEqual(auction.winner_id, self.alice.id)
        self.assertEqual(auction.final_price, Decimal("3100.00"))
        self.assertEqual(self.alice.profile.available_credits, Decimal("96900.00"))
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("0.00"))
        self.assertEqual(self.bob.profile.available_credits, Decimal("100000.00"))
        self.assertEqual(self.seller.profile.available_credits, Decimal("103100.00"))
        self.assertEqual(ProxyBid.objects.filter(auction=auction, active=True).count(), 0)
        self.assertTrue(WalletTransaction.objects.filter(user=self.alice, kind=WalletTransaction.Kind.PAYMENT, amount=Decimal("-3100.00")).exists())
        self.assertTrue(WalletTransaction.objects.filter(user=self.seller, kind=WalletTransaction.Kind.SALE, amount=Decimal("3100.00")).exists())




    def test_settlement_recomputes_price_when_stored_price_is_stale_low(self):
        auction = self.make_auction(minutes=1)
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("3000"))
        auction.current_price = Decimal("1000.00")  # simulate stale persisted display price
        auction.end_time = timezone.now() - timedelta(seconds=1)
        auction.save(update_fields=["current_price", "end_time", "updated_at"])

        close_auction(auction.id)
        auction.refresh_from_db()
        self.assertEqual(auction.final_price, Decimal("3100.00"))

    def test_settlement_never_charges_more_than_winner_maximum(self):
        auction = self.make_auction(minutes=1)
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("3000"))
        auction.current_price = Decimal("6000.00")  # simulate inconsistent/stale data
        auction.end_time = timezone.now() - timedelta(seconds=1)
        auction.save(update_fields=["current_price", "end_time", "updated_at"])

        close_auction(auction.id)
        auction.refresh_from_db()
        self.assertEqual(auction.winner_id, self.alice.id)
        self.assertEqual(auction.final_price, Decimal("5000.00"))

    def test_repeated_settlement_does_not_pay_twice(self):
        auction = self.make_auction(minutes=1)
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("3000"))
        auction.end_time = timezone.now() - timedelta(seconds=1)
        auction.save(update_fields=["end_time", "updated_at"])

        close_auction(auction.id)
        close_auction(auction.id)

        self.assertEqual(
            WalletTransaction.objects.filter(
                auction=auction,
                user=self.alice,
                kind=WalletTransaction.Kind.PAYMENT,
            ).count(),
            1,
        )
        self.assertEqual(
            WalletTransaction.objects.filter(
                auction=auction,
                user=self.seller,
                kind=WalletTransaction.Kind.SALE,
            ).count(),
            1,
        )

    def test_expired_bid_attempt_still_commits_auction_settlement(self):
        auction = self.make_auction(minutes=1)
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        auction.end_time = timezone.now() - timedelta(seconds=1)
        auction.save(update_fields=["end_time", "updated_at"])

        with self.assertRaises(AuctionError):
            place_max_bid(auction.id, self.bob, Decimal("3000"))

        auction.refresh_from_db()
        self.alice.profile.refresh_from_db()
        self.seller.profile.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ENDED)
        self.assertEqual(auction.winner_id, self.alice.id)
        self.assertEqual(self.alice.profile.available_credits, Decimal("99000.00"))
        self.assertEqual(self.seller.profile.available_credits, Decimal("101000.00"))

    def test_price_does_not_fall_when_current_leader_raises_maximum(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("3000"))
        self.assertEqual(Auction.objects.get(pk=auction.pk).current_price, Decimal("3100.00"))

        place_max_bid(auction.id, self.alice, Decimal("6000"))
        auction.refresh_from_db()
        self.assertEqual(auction.current_bidder_id, self.alice.id)
        self.assertEqual(auction.current_price, Decimal("3100.00"))
        self.alice.profile.refresh_from_db()
        self.bob.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("6000.00"))
        self.assertEqual(self.bob.profile.reserved_credits, Decimal("3000.00"))

    def test_equal_maximum_uses_earlier_proxy_as_leader(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("5000"))
        auction.refresh_from_db()
        self.assertEqual(auction.current_bidder_id, self.alice.id)
        self.assertEqual(auction.current_price, Decimal("5000.00"))


    def test_valid_bid_extends_auction_inside_anti_snipe_window(self):
        auction = self.make_auction(minutes=1)
        auction.end_time = timezone.now() + timedelta(seconds=60)
        auction.save(update_fields=["end_time", "updated_at"])
        old_end = auction.end_time

        place_max_bid(auction.id, self.alice, Decimal("5000"))

        auction.refresh_from_db()
        self.assertEqual(auction.extension_count, 1)
        self.assertGreaterEqual(auction.end_time, old_end + timedelta(seconds=119))

    def test_bid_cannot_exceed_available_wallet_capacity(self):
        auction = self.make_auction()
        with self.assertRaises(AuctionError):
            place_max_bid(auction.id, self.alice, Decimal("100000.01"))
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.available_credits, Decimal("100000.00"))
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("0.00"))

    def test_reservations_across_auctions_share_one_wallet_capacity(self):
        first = self.make_auction()
        second = self.make_auction()
        place_max_bid(first.id, self.alice, Decimal("60000.00"))
        with self.assertRaises(AuctionError):
            place_max_bid(second.id, self.alice, Decimal("50000.00"))
        self.alice.profile.refresh_from_db()
        self.assertEqual(self.alice.profile.available_credits, Decimal("40000.00"))
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("60000.00"))
        self.assertFalse(ProxyBid.objects.filter(auction=second, bidder=self.alice, active=True).exists())

    def test_cancel_releases_all_proxy_reservations_and_preserves_last_price(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        place_max_bid(auction.id, self.bob, Decimal("3000"))
        price_before_cancel = Auction.objects.get(pk=auction.pk).current_price
        cancel_auction(auction.id, self.seller)
        self.alice.profile.refresh_from_db()
        self.bob.profile.refresh_from_db()
        cancelled = auction.__class__.objects.get(pk=auction.pk)
        self.assertEqual(cancelled.status, Auction.Status.CANCELLED)
        self.assertEqual(cancelled.current_price, price_before_cancel)
        self.assertIsNone(cancelled.current_bidder_id)
        self.assertIsNone(cancelled.winner_id)
        self.assertIsNone(cancelled.final_price)
        self.assertEqual(self.alice.profile.available_credits, Decimal("100000.00"))
        self.assertEqual(self.bob.profile.available_credits, Decimal("100000.00"))
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("0.00"))
        self.assertEqual(self.bob.profile.reserved_credits, Decimal("0.00"))


    def test_expired_auction_cannot_be_cancelled_before_settlement(self):
        auction = self.make_auction(minutes=1)
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        auction.end_time = timezone.now() - timedelta(seconds=1)
        auction.save(update_fields=["end_time", "updated_at"])

        with self.assertRaisesRegex(AuctionError, "must be settled"):
            cancel_auction(auction.id, self.seller)

        auction.refresh_from_db()
        self.alice.profile.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ACTIVE)
        self.assertEqual(self.alice.profile.reserved_credits, Decimal("5000.00"))
        self.assertTrue(ProxyBid.objects.filter(auction=auction, bidder=self.alice, active=True).exists())


    def test_wallet_audit_accepts_consistent_active_reservations(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        output = StringIO()
        call_command("audit_wallets", stdout=output)
        self.assertIn("Wallet audit passed", output.getvalue())

    def test_wallet_audit_detects_a_missing_proxy_reserve_record(self):
        auction = self.make_auction()
        place_max_bid(auction.id, self.alice, Decimal("5000"))
        # Simulate manual database corruption that the audit is expected to detect.
        ProxyBid.objects.filter(auction=auction, bidder=self.alice).delete()
        with self.assertRaises(SystemExit):
            call_command("audit_wallets", stdout=StringIO())

    def test_self_bidding_is_rejected(self):
        auction = self.make_auction()
        with self.assertRaises(AuctionError):
            place_max_bid(auction.id, self.seller, Decimal("5000"))



class AuctionAPISynchronizationTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="API Category", slug="api-category")
        self.seller = User.objects.create_user("api-seller", password="Password123!")
        self.bidder = User.objects.create_user("api-bidder", password="Password123!")

    def test_api_returns_synchronized_ended_state_for_expired_auction(self):
        now = timezone.now()
        auction = Auction.objects.create(
            seller=self.seller,
            category=self.category,
            title="Expired API item",
            description="API synchronization test",
            starting_price=Decimal("1000.00"),
            minimum_increment=Decimal("100.00"),
            start_time=now - timedelta(minutes=2),
            end_time=now - timedelta(seconds=1),
            status=Auction.Status.ACTIVE,
        )
        # With no bids, the API still must synchronize the status and re-query
        # the persisted object rather than serializing the stale in-memory one.
        response = self.client.get("/api/auctions/?status=all")
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        item = next(row for row in results if row["id"] == auction.id)
        self.assertEqual(item["status"], Auction.Status.ENDED)
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ENDED)



    def test_public_json_endpoints_reject_state_changing_methods(self):
        for url in ("/api/auctions/", "/api/auctions/999999/bids/", "/auctions/999999/status/"):
            response = self.client.post(url, data={})
            self.assertEqual(response.status_code, 405, url)

    def test_upcoming_status_api_distinguishes_start_and_end_countdowns(self):
        now = timezone.now()
        auction = Auction.objects.create(
            seller=self.seller,
            category=self.category,
            title="Upcoming countdown item",
            description="Countdown synchronization test",
            starting_price=Decimal("1000.00"),
            minimum_increment=Decimal("100.00"),
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=4),
            status=Auction.Status.UPCOMING,
        )
        response = self.client.get(f"/auctions/{auction.pk}/status/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], Auction.Status.UPCOMING)
        self.assertGreater(data["start_remaining_seconds"], 0)
        self.assertGreater(data["remaining_seconds"], data["start_remaining_seconds"])

    def test_active_api_does_not_return_an_auction_that_has_expired(self):
        now = timezone.now()
        auction = Auction.objects.create(
            seller=self.seller,
            category=self.category,
            title="Expired active filter item",
            description="API filter test",
            starting_price=Decimal("1000.00"),
            minimum_increment=Decimal("100.00"),
            start_time=now - timedelta(minutes=2),
            end_time=now - timedelta(seconds=1),
            status=Auction.Status.ACTIVE,
        )
        response = self.client.get("/api/auctions/?status=active")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(auction.id, [row["id"] for row in response.json()["results"]])
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ENDED)

class SettlementTriggerSecurityTests(TestCase):
    def test_settlement_trigger_requires_bearer_secret(self):
        with patch.dict("os.environ", {"CRON_SECRET": ""}):
            response = self.client.get("/internal/cron/close-expired/")
        self.assertEqual(response.status_code, 403)

    def test_settlement_trigger_requires_configured_secret(self):
        # Even with an Authorization header, a missing configured secret denies access.
        with patch.dict("os.environ", {"CRON_SECRET": ""}):
            response = self.client.get(
                "/internal/cron/close-expired/",
                HTTP_AUTHORIZATION="Bearer not-a-secret",
            )
        self.assertEqual(response.status_code, 403)

    def test_settlement_trigger_accepts_the_configured_bearer_secret(self):
        with patch.dict("os.environ", {"CRON_SECRET": "test-cron-secret"}):
            response = self.client.get(
                "/internal/cron/close-expired/",
                HTTP_AUTHORIZATION="Bearer test-cron-secret",
            )
        self.assertEqual(response.status_code, 200)


class RequestSafetyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("request-safety-user", password="Password123!")
        self.client.force_login(self.user)

    def test_watchlist_toggle_rejects_get(self):
        response = self.client.get("/auctions/1/watchlist/")
        self.assertEqual(response.status_code, 405)

    def test_notification_center_displays_items_and_marks_them_read(self):
        item = Notification.objects.create(
            user=self.user,
            message="Your bid is currently leading.",
            link="/auctions/12/",
        )
        response = self.client.get("/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your bid is currently leading.")
        self.assertContains(response, 'href="/auctions/12/"')

        response = self.client.post(
            "/notifications/read/",
            data={"next": "/notifications/"},
        )
        self.assertRedirects(response, "/notifications/", fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertTrue(item.is_read)

    def test_notification_read_does_not_redirect_to_external_host(self):
        response = self.client.post(
            "/notifications/read/",
            data={},
            HTTP_REFERER="https://example-evil.invalid/",
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("example-evil.invalid", response["Location"])


class CloseExpiredCommandFailureTests(TestCase):
    def test_command_returns_failure_when_an_auction_cannot_be_settled(self):
        category, _ = Category.objects.get_or_create(
            slug="electronics", defaults={"name": "Electronics"}
        )
        seller = User.objects.create_user("close-command-seller", password="Password123!")
        now = timezone.now()
        Auction.objects.create(
            seller=seller,
            category=category,
            title="Expired command failure",
            description="Regression test",
            starting_price=Decimal("100.00"),
            minimum_increment=Decimal("10.00"),
            start_time=now - timedelta(hours=1),
            end_time=now - timedelta(minutes=1),
            status=Auction.Status.ACTIVE,
        )
        with patch(
            "auction.management.commands.close_expired.close_auction",
            side_effect=RuntimeError("synthetic settlement failure"),
        ):
            with self.assertRaises(CommandError):
                call_command("close_expired", stdout=StringIO(), stderr=StringIO())


class SeedDemoCommandTests(TestCase):
    @override_settings(DEBUG=True)
    def test_seeded_ended_auctions_have_a_bid_and_settlement(self):
        # The seed command is intentionally blocked when DEBUG=False. Override
        # DEBUG for this isolated test so a developer's .env / shell settings do
        # not make the test environment-dependent.
        # Regression: ended demo lots must receive bids before their end times
        # are moved into the past and they are settled.
        call_command("seed_demo", reset=True, stdout=StringIO(), stderr=StringIO())
        ended = list(Auction.objects.filter(status=Auction.Status.ENDED))
        self.assertEqual(len(ended), 3)
        for auction in ended:
            self.assertTrue(auction.bids.exists(), auction.title)
            self.assertIsNotNone(auction.winner_id, auction.title)
            self.assertIsNotNone(auction.final_price, auction.title)
            self.assertIsNotNone(auction.settled_at, auction.title)

    @override_settings(DEBUG=False)
    def test_seeding_is_blocked_when_debug_is_off_without_explicit_override(self):
        # Even if a developer has set the opt-in variable in their shell, the
        # safety guard must be exercised deterministically by this test.
        with patch.dict("os.environ", {"ALLOW_DEMO_SEED_IN_PRODUCTION": ""}):
            with self.assertRaisesRegex(CommandError, "Demo seeding is disabled"):
                call_command("seed_demo", stdout=StringIO(), stderr=StringIO())


class AuctionListSynchronizationTests(TestCase):
    def test_all_auction_listing_synchronizes_expired_lot_and_renders(self):
        category = Category.objects.create(name="List Sync Category", slug="list-sync-category")
        seller = User.objects.create_user("list-sync-seller", password="Password123!")
        now = timezone.now()
        auction = Auction.objects.create(
            seller=seller,
            category=category,
            title="Expired listing synchronization",
            description="Regression test",
            starting_price=Decimal("1000.00"),
            minimum_increment=Decimal("100.00"),
            start_time=now - timedelta(minutes=10),
            end_time=now - timedelta(seconds=1),
            status=Auction.Status.ACTIVE,
        )
        response = self.client.get("/auctions/?status=all")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Expired listing synchronization")
        auction.refresh_from_db()
        self.assertEqual(auction.status, Auction.Status.ENDED)


class WalletAuditIntegrityTests(TestCase):
    def test_wallet_audit_detects_user_without_profile(self):
        user = User.objects.create_user("missing-profile-user", password="Password123!")
        user.profile.delete()
        with self.assertRaises(SystemExit):
            call_command("audit_wallets", stdout=StringIO(), stderr=StringIO())
