from datetime import timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from .models import Auction, Bid, Notification, Profile, ProxyBid, WalletTransaction


class AuctionError(Exception):
    pass


class _ExpiredBidAttempt(Exception):
    """Internal control flow: commit the attempted bid transaction as rolled back, then settle."""


def _notify(user: User, message: str, link: str = ""):
    Notification.objects.create(user=user, message=message, link=link)


def _lock_profiles(user_ids):
    ids = sorted(set(int(v) for v in user_ids if v))
    if not ids:
        return {}
    profiles = Profile.objects.select_for_update().filter(user_id__in=ids).order_by("user_id")
    return {p.user_id: p for p in profiles}


def _apply_balance_delta(profile: Profile, delta: Decimal, *, auction=None, bid=None, kind=None, note=""):
    profile.available_credits += delta
    if profile.available_credits < 0:
        raise AuctionError("Insufficient available credits.")
    profile.save(update_fields=["available_credits"])
    WalletTransaction.objects.create(
        user=profile.user,
        auction=auction,
        bid=bid,
        kind=kind,
        amount=delta,
        balance_after=profile.available_credits,
        note=note,
    )


def _rank_proxies(proxies):
    return sorted(proxies, key=lambda p: (-p.max_amount, p.priority_at, p.id))


def _current_winner_and_price(auction, proxies):
    """Return the leading proxy and a price that never moves backwards."""
    ranked = _rank_proxies(proxies)
    if not ranked:
        return None, Decimal("0.00")

    winner = ranked[0]
    if len(ranked) == 1:
        calculated_price = auction.starting_price
    else:
        runner_up = ranked[1]
        calculated_price = max(
            auction.starting_price,
            min(winner.max_amount, runner_up.max_amount + auction.minimum_increment),
        )

    # Increasing a leader's maximum, or adding a lower proxy bid, must never
    # lower a price already shown to users.
    return winner, max(auction.current_price, calculated_price)


def _maybe_extend(auction, now):
    # Import from settings here so this service stays easy to test.
    from django.conf import settings

    if auction.end_time <= now:
        return False
    window = int(getattr(settings, "ANTI_SNIPE_WINDOW_SECONDS", 120))
    extension = int(getattr(settings, "ANTI_SNIPE_EXTENSION_SECONDS", 120))
    seconds_left = (auction.end_time - now).total_seconds()
    if seconds_left <= window:
        auction.end_time = auction.end_time + timedelta(seconds=extension)
        auction.extension_count += 1
        auction.save(update_fields=["end_time", "extension_count", "updated_at"])
        return True
    return False


def sync_auction_status(auction: Auction) -> Auction:
    """Move scheduled auctions into live state. Close expired auctions lazily."""
    now = timezone.now()
    if auction.status in {Auction.Status.CANCELLED, Auction.Status.ENDED}:
        return auction
    # Expiry always wins over the start-time state. This also repairs stale or
    # inconsistent rows imported from older data.
    if now >= auction.end_time:
        close_auction(auction.pk)
        return Auction.objects.get(pk=auction.pk)
    if now < auction.start_time:
        if auction.status != Auction.Status.UPCOMING:
            auction.status = Auction.Status.UPCOMING
            auction.save(update_fields=["status", "updated_at"])
        return auction
    if auction.status != Auction.Status.ACTIVE:
        auction.status = Auction.Status.ACTIVE
        auction.save(update_fields=["status", "updated_at"])
    return auction


def _release_proxy_locked(proxy, profiles, *, note=""):
    if not proxy.active:
        return
    amount = proxy.reserved_amount
    if amount > 0:
        profile = profiles[proxy.bidder_id]
        _apply_balance_delta(
            profile,
            amount,
            auction=proxy.auction,
            kind=WalletTransaction.Kind.RELEASE,
            note=note or "Released bid reserve",
        )
    proxy.active = False
    proxy.reserved_amount = Decimal("0.00")
    proxy.save(update_fields=["active", "reserved_amount", "updated_at"])


def place_max_bid(auction_id: int, bidder: User, max_amount: Decimal):
    """Place or increase a maximum proxy bid with atomic wallet reservations.

    Every active proxy retains its maximum and reserves enough credits to cover
    it. Losing proxy bids remain eligible to become the leader if the current
    leader is outbid. The auction row serializes bids on PostgreSQL.
    """
    max_amount = Decimal(str(max_amount)).quantize(Decimal("0.01"))
    try:
        with transaction.atomic():
            auction = Auction.objects.select_for_update().select_related("seller").get(pk=auction_id)
            now = timezone.now()
            if auction.status in {Auction.Status.CANCELLED, Auction.Status.ENDED}:
                raise AuctionError("This auction is not currently accepting bids.")
            if now >= auction.end_time:
                # Settle after leaving/rolling back this transaction. Raising an
                # internal exception here avoids rolling settlement back with the
                # rejected bid attempt.
                raise _ExpiredBidAttempt()
            if now < auction.start_time:
                raise AuctionError("This auction is not currently accepting bids.")
            if auction.status != Auction.Status.ACTIVE:
                auction.status = Auction.Status.ACTIVE
                auction.save(update_fields=["status", "updated_at"])
            if auction.seller_id == bidder.id:
                raise AuctionError("Sellers cannot bid on their own auctions.")
            if max_amount <= 0:
                raise AuctionError("Your maximum bid must be greater than zero.")

            existing = ProxyBid.objects.select_for_update().filter(auction=auction, bidder=bidder).first()
            old_max = existing.max_amount if existing and existing.active else Decimal("0.00")
            if existing and existing.active and max_amount <= old_max:
                raise AuctionError(
                    f"Your new maximum must be higher than your current maximum ({old_max:.2f})."
                )

            current_min = (
                auction.starting_price
                if not auction.bids.exists()
                else auction.current_price + auction.minimum_increment
            )
            if max_amount < current_min:
                raise AuctionError(f"Maximum bid must be at least {current_min:.2f} credits.")

            active_proxy_user_ids = list(
                ProxyBid.objects.filter(auction=auction, active=True).values_list("bidder_id", flat=True)
            )
            profiles = _lock_profiles(active_proxy_user_ids + [bidder.id, auction.seller_id])
            bidder_profile = profiles.get(bidder.id)
            if bidder_profile is None:
                raise AuctionError("Your wallet is unavailable. Please try again.")

            previous_reserve = (
                existing.reserved_amount if existing and existing.active else Decimal("0.00")
            )
            available_capacity = bidder_profile.available_credits + previous_reserve
            if max_amount > available_capacity:
                raise AuctionError("You do not have enough available credits for that maximum bid.")

            if existing is None:
                existing = ProxyBid.objects.create(
                    auction=auction,
                    bidder=bidder,
                    max_amount=max_amount,
                    reserved_amount=Decimal("0.00"),
                    active=True,
                    priority_at=now,
                )
            else:
                existing.max_amount = max_amount
                existing.active = True
                if not existing.reserved_amount:
                    existing.priority_at = now
                existing.save(update_fields=["max_amount", "active", "priority_at", "updated_at"])

            active_proxies = list(
                ProxyBid.objects.select_for_update().filter(auction=auction, active=True)
            )
            old_leader_id = auction.current_bidder_id
            winner, price = _current_winner_and_price(auction, active_proxies)
            if winner is None:  # Defensive; the just-created proxy should make this impossible.
                raise AuctionError("The bid could not be ranked. Please try again.")

            # Reserve each bidder's own maximum. Do not deactivate/release losing
            # bidders: those proxy bids must remain capable of automatically winning.
            for proxy in active_proxies:
                profile = profiles.get(proxy.bidder_id)
                if profile is None:
                    raise AuctionError("A participating wallet is unavailable. Please try again.")
                desired_reserve = proxy.max_amount
                current_reserve = proxy.reserved_amount
                delta = desired_reserve - current_reserve
                if delta > 0:
                    _apply_balance_delta(
                        profile,
                        -delta,
                        auction=auction,
                        kind=WalletTransaction.Kind.RESERVE,
                        note="Reserved maximum proxy bid",
                    )
                elif delta < 0:
                    _apply_balance_delta(
                        profile,
                        -delta,
                        auction=auction,
                        kind=WalletTransaction.Kind.RELEASE,
                        note="Reduced proxy reserve",
                    )
                if proxy.reserved_amount != desired_reserve or not proxy.active:
                    proxy.reserved_amount = desired_reserve
                    proxy.active = True
                    proxy.save(update_fields=["reserved_amount", "active", "updated_at"])

            auction.current_bidder = winner.bidder
            auction.current_price = price
            _maybe_extend(auction, now)
            auction.save(
                update_fields=["current_bidder", "current_price", "end_time", "extension_count", "updated_at"]
            )

            bid = Bid.objects.create(
                auction=auction,
                bidder=bidder,
                max_amount=max_amount,
                displayed_amount=price,
            )

            if old_leader_id and old_leader_id != winner.bidder_id:
                previous_leader = User.objects.filter(pk=old_leader_id).first()
                if previous_leader:
                    _notify(
                        previous_leader,
                        f"You were outbid on '{auction.title}'. Current price: {price:.2f} credits.",
                        f"/auctions/{auction.pk}/",
                    )

            if winner.bidder_id == bidder.id:
                _notify(
                    bidder,
                    f"Your bid is currently leading on '{auction.title}' at {price:.2f} credits.",
                    f"/auctions/{auction.pk}/",
                )
            else:
                _notify(
                    bidder,
                    f"Your maximum bid was recorded for '{auction.title}'. Current price: {price:.2f} credits.",
                    f"/auctions/{auction.pk}/",
                )
            return auction, bid

    except _ExpiredBidAttempt:
        close_auction(auction_id)
        raise AuctionError("This auction is not currently accepting bids.")

def close_auction(auction_id: int):
    with transaction.atomic():
        auction = Auction.objects.select_for_update().select_related("seller").get(pk=auction_id)
        now = timezone.now()
        if auction.status == Auction.Status.CANCELLED:
            return auction
        if auction.status == Auction.Status.ENDED:
            return auction
        if auction.end_time > now:
            if now >= auction.start_time and auction.status != Auction.Status.ACTIVE:
                auction.status = Auction.Status.ACTIVE
                auction.save(update_fields=["status", "updated_at"])
            return auction

        proxies = list(ProxyBid.objects.select_for_update().filter(auction=auction, active=True))
        user_ids = [auction.seller_id] + [p.bidder_id for p in proxies]
        profiles = _lock_profiles(user_ids)
        winner_proxy = None
        if proxies:
            ranked = _rank_proxies(proxies)
            winner_proxy = ranked[0]
            # Recompute from the active proxy maxima at settlement instead of
            # trusting a possibly stale stored display price. Keep prices
            # monotonic, but never charge above the winner's reserved maximum.
            _, calculated_price = _current_winner_and_price(auction, proxies)
            final_price = min(
                winner_proxy.max_amount,
                max(auction.starting_price, calculated_price),
            )
            winner_profile = profiles[winner_proxy.bidder_id]
            reserve = winner_proxy.reserved_amount
            if reserve > 0:
                _apply_balance_delta(
                    winner_profile,
                    reserve,
                    auction=auction,
                    kind=WalletTransaction.Kind.RELEASE,
                    note="Released winning bid reserve before settlement",
                )
            winner_proxy.active = False
            winner_proxy.reserved_amount = Decimal("0.00")
            winner_proxy.save(update_fields=["active", "reserved_amount", "updated_at"])

            _apply_balance_delta(
                winner_profile,
                -final_price,
                auction=auction,
                kind=WalletTransaction.Kind.PAYMENT,
                note="Final winning auction payment",
            )
            seller_profile = profiles[auction.seller_id]
            _apply_balance_delta(
                seller_profile,
                final_price,
                auction=auction,
                kind=WalletTransaction.Kind.SALE,
                note="Auction sale proceeds",
            )

            _notify(
                winner_proxy.bidder,
                f"You won '{auction.title}' for {final_price:.2f} credits.",
                f"/auctions/{auction.pk}/",
            )
            _notify(
                auction.seller,
                f"'{auction.title}' sold for {final_price:.2f} credits.",
                f"/auctions/{auction.pk}/",
            )
            auction.winner = winner_proxy.bidder
            auction.final_price = final_price
            auction.current_bidder = winner_proxy.bidder
            auction.current_price = final_price
        else:
            auction.final_price = None
            auction.winner = None
            auction.current_bidder = None
            auction.current_price = Decimal("0.00")

        # Defensive cleanup: there should be no other active proxies, but release if there are.
        for proxy in ProxyBid.objects.select_for_update().filter(auction=auction, active=True):
            _release_proxy_locked(proxy, profiles, note="Released after auction settlement")

        auction.status = Auction.Status.ENDED
        auction.settled_at = now
        auction.save(
            update_fields=[
                "status",
                "winner",
                "final_price",
                "current_bidder",
                "current_price",
                "settled_at",
                "updated_at",
            ]
        )
        return auction


def cancel_auction(auction_id: int, actor: User):
    with transaction.atomic():
        auction = Auction.objects.select_for_update().get(pk=auction_id)
        if auction.seller_id != actor.id:
            raise AuctionError("Only the seller can cancel this auction.")
        if auction.status in {Auction.Status.ENDED, Auction.Status.CANCELLED}:
            raise AuctionError("This auction is already closed.")
        # The deadline, not a lazily updated status field, decides whether the
        # seller can cancel. Otherwise a seller could cancel an already-expired
        # auction before the scheduler/page request settles it.
        if auction.end_time <= timezone.now():
            raise AuctionError("This auction has expired and must be settled; it can no longer be cancelled.")
        proxies = list(ProxyBid.objects.select_for_update().filter(auction=auction, active=True))
        profiles = _lock_profiles([p.bidder_id for p in proxies] + [auction.seller_id])
        for proxy in proxies:
            _release_proxy_locked(proxy, profiles, note="Released because auction was cancelled")
        auction.status = Auction.Status.CANCELLED
        auction.current_bidder = None
        # Preserve the last displayed price for history and avoid a visible
        # price drop when an auction is cancelled. Cancellation is not a sale.
        auction.winner = None
        auction.final_price = None
        auction.settled_at = None
        auction.save(
            update_fields=[
                "status", "current_bidder", "winner", "final_price", "settled_at", "updated_at"
            ]
        )
        for proxy in proxies:
            _notify(proxy.bidder, f"Auction '{auction.title}' was cancelled. Your reserve was released.", f"/auctions/{auction.pk}/")
        return auction
