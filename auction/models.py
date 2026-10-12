from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

MONEY_MIN = Decimal("0.01")


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    available_credits = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("100000.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def reserved_credits(self):
        return self.user.proxy_bids.filter(active=True).aggregate(
            total=models.Sum("reserved_amount")
        )["total"] or Decimal("0.00")

    @property
    def wallet_total(self):
        return self.available_credits + self.reserved_credits

    def __str__(self):
        return f"{self.user.username}'s profile"


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Auction(models.Model):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        ACTIVE = "active", "Live"
        ENDED = "ended", "Ended"
        CANCELLED = "cancelled", "Cancelled"

    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name="auctions")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="auctions")
    title = models.CharField(max_length=160)
    description = models.TextField()
    image = models.ImageField(upload_to="auctions/", blank=True, null=True)
    starting_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(MONEY_MIN)],
    )
    minimum_increment = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("100.00"),
        validators=[MinValueValidator(MONEY_MIN)],
    )
    current_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    current_bidder = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leading_auctions",
    )
    winner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="won_auctions",
    )
    final_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)
    view_count = models.PositiveIntegerField(default=0)
    extension_count = models.PositiveIntegerField(default=0)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "end_time"], name="auc_status_end_idx"),
            models.Index(fields=["category", "status"], name="auc_cat_status_idx"),
            models.Index(fields=["seller", "status"], name="auc_seller_status_idx"),
        ]

    @property
    def effective_price(self):
        return self.current_price if self.current_price > 0 else self.starting_price

    @property
    def next_bid_amount(self):
        return self.starting_price if not self.bids.exists() else self.current_price + self.minimum_increment

    @property
    def seconds_remaining(self):
        if self.status in {self.Status.ENDED, self.Status.CANCELLED}:
            return 0
        return max(0, int((self.end_time - timezone.now()).total_seconds()))

    @property
    def is_ending_soon(self):
        return self.status == self.Status.ACTIVE and 0 < self.seconds_remaining <= 600

    def __str__(self):
        return self.title


class ProxyBid(models.Model):
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="proxy_bids")
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name="proxy_bids")
    max_amount = models.DecimalField(max_digits=14, decimal_places=2)
    reserved_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    active = models.BooleanField(default=False)
    priority_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["auction", "bidder"], name="uniq_proxy_auction_bidder")
        ]
        indexes = [
            models.Index(fields=["auction", "active", "max_amount"], name="proxy_auc_active_max_idx"),
        ]
        ordering = ["-max_amount", "priority_at", "id"]

    def __str__(self):
        return f"{self.bidder.username}: {self.auction.title} ({self.max_amount})"


class Bid(models.Model):
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="bids")
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bids")
    max_amount = models.DecimalField(max_digits=14, decimal_places=2)
    displayed_amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["auction", "-created_at"], name="bid_auc_created_idx"),
            models.Index(fields=["bidder", "-created_at"], name="bid_user_created_idx"),
        ]

    def __str__(self):
        return f"{self.bidder.username} bid on {self.auction.title}"


class WalletTransaction(models.Model):
    class Kind(models.TextChoices):
        INITIAL = "initial", "Initial credits"
        RESERVE = "reserve", "Bid reserve"
        RELEASE = "release", "Reserve release"
        PAYMENT = "payment", "Winning payment"
        SALE = "sale", "Seller proceeds"
        ADJUSTMENT = "adjustment", "Admin adjustment"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wallet_transactions")
    auction = models.ForeignKey(Auction, on_delete=models.SET_NULL, null=True, blank=True, related_name="wallet_transactions")
    bid = models.ForeignKey(Bid, on_delete=models.SET_NULL, null=True, blank=True, related_name="wallet_transactions")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="wallet_user_created_idx"),
        ]


class Watchlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="watchlist_items")
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="watchers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "auction"], name="uniq_watch_user_auction")
        ]


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=255)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"], name="notif_user_read_idx"),
        ]


class Report(models.Model):
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reports")
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="reports")
    reason = models.CharField(max_length=80)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at", "-id"]
