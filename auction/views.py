from decimal import Decimal
import hmac
import os

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import AuctionForm, MaxBidForm, ProfileForm, RegistrationForm, ReportForm
from .models import Auction, Bid, Category, Notification, Profile, Report, Watchlist
from .services import AuctionError, cancel_auction, close_auction, place_max_bid, sync_auction_status


def _sync_queryset(auctions):
    for auction in auctions:
        sync_auction_status(auction)
    return auctions


def _sync_transitioning_auctions(limit=25):
    """Settle oldest expired lots before transitioning scheduled lots to live."""
    now = timezone.now()
    open_statuses = [Auction.Status.UPCOMING, Auction.Status.ACTIVE]
    expired_ids = list(
        Auction.objects.filter(status__in=open_statuses, end_time__lte=now)
        .order_by("end_time", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    for auction_id in expired_ids:
        close_auction(auction_id)

    remaining = max(0, limit - len(expired_ids))
    if remaining:
        starting_ids = list(
            Auction.objects.filter(
                Q(
                    status=Auction.Status.UPCOMING,
                    start_time__lte=now,
                    end_time__gt=now,
                )
                | Q(
                    status=Auction.Status.ACTIVE,
                    start_time__gt=now,
                    end_time__gt=now,
                )
            )
            .order_by("start_time", "pk")
            .values_list("pk", flat=True)[:remaining]
        )
        for auction_id in starting_ids:
            auction = Auction.objects.only("id", "status", "start_time", "end_time").get(pk=auction_id)
            sync_auction_status(auction)


def home(request):
    _sync_transitioning_auctions()
    now = timezone.now()
    active_qs = list(
        Auction.objects.filter(
            status=Auction.Status.ACTIVE,
            start_time__lte=now,
            end_time__gt=now,
        )
        .select_related("category", "seller", "current_bidder")
        .order_by("end_time")[:8]
    )
    active = []
    for auction in active_qs:
        synced = sync_auction_status(auction)
        if synced.status == Auction.Status.ACTIVE:
            active.append(synced)
    upcoming_qs = list(
        Auction.objects.filter(
            status=Auction.Status.UPCOMING,
            start_time__gt=now,
            end_time__gt=now,
        ).select_related("category", "seller").order_by("start_time")[:6]
    )
    upcoming = []
    for auction in upcoming_qs:
        synced = sync_auction_status(auction)
        if synced.status == Auction.Status.UPCOMING:
            upcoming.append(synced)
    categories = Category.objects.all()
    return render(request, "auction/home.html", {"active": active, "upcoming": upcoming, "categories": categories})


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Account created. You received 100,000 demo credits.")
        return redirect("dashboard")
    return render(request, "auction/register.html", {"form": form})


def auction_list(request):
    _sync_transitioning_auctions()
    now = timezone.now()
    qs = Auction.objects.select_related("category", "seller", "current_bidder")
    status = request.GET.get("status", "active")
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    sort = request.GET.get("sort", "ending")

    if status == "active":
        qs = qs.filter(
            status=Auction.Status.ACTIVE,
            start_time__lte=now,
            end_time__gt=now,
        )
    elif status == "upcoming":
        qs = qs.filter(
            status=Auction.Status.UPCOMING,
            start_time__gt=now,
            end_time__gt=now,
        )
    elif status == "ended":
        qs = qs.filter(
            Q(status=Auction.Status.ENDED)
            | Q(status__in=[Auction.Status.UPCOMING, Auction.Status.ACTIVE], end_time__lte=now)
        )
    elif status == "all":
        pass
    else:
        status = "active"
        qs = qs.filter(status=Auction.Status.ACTIVE)

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if category:
        qs = qs.filter(category__slug=category)
    if sort == "price_low":
        qs = qs.order_by("current_price", "starting_price")
    elif sort == "price_high":
        qs = qs.order_by("-current_price", "-starting_price")
    elif sort == "newest":
        qs = qs.order_by("-created_at")
    else:
        qs = qs.order_by("end_time")

    selected = list(qs[:100])
    auctions = []
    for auction in selected:
        current = sync_auction_status(auction)
        if status != "all" and current.status != status:
            continue
        auctions.append(current)

    return render(
        request,
        "auction/auction_list.html",
        {"auctions": auctions, "categories": Category.objects.all(), "filters": request.GET},
    )


def auction_detail(request, pk):
    auction = get_object_or_404(
        Auction.objects.select_related("seller", "category", "current_bidder", "winner"), pk=pk
    )
    sync_auction_status(auction)
    auction.refresh_from_db()

    viewed_key = f"auction_viewed_{auction.pk}"
    if not request.session.get(viewed_key):
        Auction.objects.filter(pk=auction.pk).update(view_count=F("view_count") + 1)
        request.session[viewed_key] = True
        auction.view_count += 1

    bids = auction.bids.select_related("bidder").order_by("-created_at")[:50]
    watching = request.user.is_authenticated and Watchlist.objects.filter(user=request.user, auction=auction).exists()
    proxy = None
    if request.user.is_authenticated:
        proxy = auction.proxy_bids.filter(bidder=request.user, active=True).first()

    return render(
        request,
        "auction/auction_detail.html",
        {
            "auction": auction,
            "bids": bids,
            "bid_form": MaxBidForm(initial={"max_amount": auction.next_bid_amount}),
            "watching": watching,
            "proxy": proxy,
        },
    )


@login_required
def create_auction(request):
    form = AuctionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        auction = form.save(commit=False)
        auction.seller = request.user
        now = timezone.now()
        auction.status = Auction.Status.UPCOMING if auction.start_time > now else Auction.Status.ACTIVE
        auction.current_price = Decimal("0.00")
        auction.save()
        messages.success(request, "Auction published successfully.")
        return redirect("auction_detail", pk=auction.pk)
    return render(request, "auction/create_auction.html", {"form": form})


@login_required
@require_POST
def place_bid(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    form = MaxBidForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a valid maximum bid amount.")
        return redirect("auction_detail", pk=pk)
    try:
        auction, bid = place_max_bid(pk, request.user, form.cleaned_data["max_amount"])
    except AuctionError as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, "The bid could not be processed. Please try again.")
    else:
        messages.success(request, f"Bid accepted. Current price: {auction.current_price:.2f} credits.")
    return redirect("auction_detail", pk=pk)


@login_required
@require_POST
def toggle_watchlist(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    item, created = Watchlist.objects.get_or_create(user=request.user, auction=auction)
    if not created:
        item.delete()
        messages.info(request, "Removed from watchlist.")
    else:
        messages.success(request, "Added to watchlist.")
    return redirect("auction_detail", pk=pk)


@login_required
@require_POST
def close_my_auction(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    if auction.seller_id != request.user.id:
        messages.error(request, "Only the seller can finalize this auction.")
    elif auction.end_time > timezone.now():
        messages.error(request, "You can only finalize an auction after its end time.")
    else:
        close_auction(pk)
        messages.success(request, "Auction finalized and wallets settled.")
    return redirect("auction_detail", pk=pk)


@login_required
@require_POST
def cancel_my_auction(request, pk):
    try:
        cancel_auction(pk, request.user)
    except AuctionError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Auction cancelled and active reserve released.")
    return redirect("auction_detail", pk=pk)


@require_GET
def auction_status(request, pk):
    auction = get_object_or_404(Auction.objects.select_related("current_bidder"), pk=pk)
    sync_auction_status(auction)
    auction.refresh_from_db()
    return JsonResponse(
        {
            "id": auction.pk,
            "status": auction.status,
            "status_label": auction.get_status_display(),
            "current_price": f"{auction.effective_price:.2f}",
            "current_bidder": auction.current_bidder.username if auction.current_bidder_id else None,
            # The page countdown targets start_time for upcoming auctions and
            # end_time for live auctions. Expose both explicitly so client polling
            # cannot silently switch an upcoming auction to its end countdown.
            "remaining_seconds": auction.seconds_remaining,
            "start_remaining_seconds": max(0, int((auction.start_time - timezone.now()).total_seconds())),
            "next_bid": f"{auction.next_bid_amount:.2f}",
            "bid_count": auction.bids.count(),
            "view_count": auction.view_count,
            "extension_count": auction.extension_count,
        }
    )


@login_required
def dashboard(request):
    _sync_transitioning_auctions()
    my_auctions = request.user.auctions.all()
    for auction in list(
        my_auctions.filter(status__in=[Auction.Status.UPCOMING, Auction.Status.ACTIVE])
        .order_by("end_time", "pk")[:100]
    ):
        sync_auction_status(auction)
    stats = {
        "selling": my_auctions.filter(status=Auction.Status.ACTIVE).count(),
        "upcoming": my_auctions.filter(status=Auction.Status.UPCOMING).count(),
        "ended": my_auctions.filter(status=Auction.Status.ENDED).count(),
        "bids": request.user.bids.count(),
        "watching": request.user.watchlist_items.count(),
    }
    return render(request, "auction/dashboard.html", {"stats": stats, "recent": my_auctions.select_related("category").order_by("-created_at")[:5]})


@login_required
def wallet(request):
    _sync_transitioning_auctions()
    profile = request.user.profile
    txs = request.user.wallet_transactions.select_related("auction")[:100]
    return render(
        request,
        "auction/wallet.html",
        {"profile": profile, "reserved": profile.reserved_credits, "total": profile.wallet_total, "transactions": txs},
    )


@login_required
def my_auctions(request):
    _sync_transitioning_auctions()
    for auction in list(
        request.user.auctions.filter(status__in=[Auction.Status.UPCOMING, Auction.Status.ACTIVE])
        .order_by("end_time", "pk")[:100]
    ):
        sync_auction_status(auction)
    qs = request.user.auctions.select_related("category", "current_bidder").annotate(
        bid_count=Count("bids", distinct=True), watcher_count=Count("watchers", distinct=True)
    )
    return render(request, "auction/my_auctions.html", {"auctions": qs})


@login_required
def my_bids(request):
    bids = request.user.bids.select_related("auction").order_by("-created_at")
    return render(request, "auction/my_bids.html", {"bids": bids})


@login_required
def watchlist(request):
    _sync_transitioning_auctions()
    items = request.user.watchlist_items.select_related("auction", "auction__category", "auction__current_bidder")
    return render(request, "auction/watchlist.html", {"items": items})


@login_required
def profile_view(request):
    profile = request.user.profile
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        request.user.first_name = form.cleaned_data.get("first_name", "").strip()
        request.user.last_name = form.cleaned_data.get("last_name", "").strip()
        request.user.save(update_fields=["first_name", "last_name"])
        messages.success(request, "Profile updated.")
        return redirect("profile")
    form.fields["first_name"].initial = request.user.first_name
    form.fields["last_name"].initial = request.user.last_name
    return render(request, "auction/profile.html", {"form": form, "profile": profile})


@login_required
def notification_center(request):
    items = list(request.user.notifications.all()[:100])
    allowed_hosts = {request.get_host()}
    for item in items:
        link = item.link or ""
        item.safe_link = (
            link
            if link and url_has_allowed_host_and_scheme(
                link,
                allowed_hosts=allowed_hosts,
                require_https=request.is_secure(),
            )
            else ""
        )
    return render(request, "auction/notifications.html", {"notifications": items})


@login_required
@require_POST
def mark_notifications_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    target = request.POST.get("next") or request.META.get("HTTP_REFERER") or ""
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(target)
    return redirect("dashboard")


@login_required
@require_POST
def report_auction(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    form = ReportForm(request.POST)
    if form.is_valid():
        report = form.save(commit=False)
        report.reporter = request.user
        report.auction = auction
        report.save()
        messages.success(request, "Report submitted to moderation.")
    else:
        messages.error(request, "Please select a valid report reason.")
    return redirect("auction_detail", pk=pk)


@login_required
def seller_analytics(request):
    _sync_transitioning_auctions()
    auctions = request.user.auctions.all()
    total_views = auctions.aggregate(total=Sum("view_count"))["total"] or 0
    total_bids = Bid.objects.filter(auction__seller=request.user).count()
    revenue = request.user.wallet_transactions.filter(kind="sale").aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    return render(
        request,
        "auction/seller_analytics.html",
        {
            "total_views": total_views,
            "total_bids": total_bids,
            "revenue": revenue,
            "active": auctions.filter(status=Auction.Status.ACTIVE).count(),
            "ended": auctions.filter(status=Auction.Status.ENDED).count(),
        },
    )


@require_GET
def api_auctions(request):
    _sync_transitioning_auctions()
    now = timezone.now()
    requested_status = request.GET.get("status", "active")
    valid_statuses = {"active", "upcoming", "ended", "cancelled"}
    if requested_status not in valid_statuses | {"all"}:
        requested_status = "active"

    qs = Auction.objects.select_related("category", "current_bidder")
    if requested_status == "active":
        qs = qs.filter(
            status=Auction.Status.ACTIVE,
            start_time__lte=now,
            end_time__gt=now,
        )
    elif requested_status == "upcoming":
        qs = qs.filter(
            status=Auction.Status.UPCOMING,
            start_time__gt=now,
            end_time__gt=now,
        )
    elif requested_status == "ended":
        qs = qs.filter(
            Q(status=Auction.Status.ENDED)
            | Q(status__in=[Auction.Status.UPCOMING, Auction.Status.ACTIVE], end_time__lte=now)
        )
    elif requested_status == "cancelled":
        qs = qs.filter(status=Auction.Status.CANCELLED)

    data = []
    for auction in qs.order_by("end_time", "id")[:100]:
        # Synchronize returned records too, so response fields never come from
        # a stale in-memory instance if an auction expired between the batch
        # sweep and the result query.
        auction = sync_auction_status(auction)
        if requested_status != "all" and auction.status != requested_status:
            continue
        data.append(
            {
                "id": auction.id,
                "title": auction.title,
                "category": auction.category.name,
                "status": auction.status,
                "current_price": str(auction.effective_price),
                "end_time": auction.end_time.isoformat(),
            }
        )
    return JsonResponse({"results": data})


@require_GET
def api_bids(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    sync_auction_status(auction)
    bids = auction.bids.select_related("bidder").order_by("-created_at")[:100]
    return JsonResponse(
        {
            "auction": auction.pk,
            "results": [
                {
                    "bidder": bid.bidder.username,
                    # Keep `amount` for backwards compatibility; this is the
                    # public price after the proxy maximum was submitted, not
                    # the bidder's private maximum.
                    "amount": f"{bid.displayed_amount:.2f}",
                    "price_after": f"{bid.displayed_amount:.2f}",
                    "created_at": bid.created_at.isoformat(),
                }
                for bid in bids
            ],
        }
    )


@require_GET
def cron_close_expired(request):
    """Optional bearer-token endpoint for a configured hosting scheduler."""
    secret = os.environ.get("CRON_SECRET", "")
    authorization = request.headers.get("Authorization", "")
    scheme, separator, credential = authorization.partition(" ")
    supplied = credential.strip() if separator and scheme.lower() == "bearer" else ""
    if not secret or not supplied or not hmac.compare_digest(supplied, secret):
        return HttpResponseForbidden("Forbidden")

    expired_ids = list(
        Auction.objects.filter(
            status__in=[Auction.Status.UPCOMING, Auction.Status.ACTIVE],
            end_time__lte=timezone.now(),
        ).order_by("id").values_list("id", flat=True)[:500]
    )
    settled = 0
    failed = 0
    for auction_id in expired_ids:
        try:
            result = close_auction(auction_id)
            if result.status == Auction.Status.ENDED:
                settled += 1
        except Exception:
            # Don't expose exception details or secrets in the HTTP response.
            failed += 1

    payload = {"checked": len(expired_ids), "settled": settled, "failed": failed}
    return JsonResponse(payload, status=500 if failed else 200)
