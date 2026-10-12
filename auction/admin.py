from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Auction, Bid, Category, Notification, Profile, ProxyBid, Report, WalletTransaction, Watchlist


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "available_credits", "created_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("user", "available_credits", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "category", "status", "current_price", "current_bidder", "end_time")
    list_filter = ("status", "category")
    search_fields = ("title", "description", "seller__username")
    # Keep fields that affect bid ranking, timing, ownership or settlement
    # immutable in the admin. Changing them outside auction services can make
    # wallet reserves disagree with the auction state.
    readonly_fields = (
        "seller", "starting_price", "minimum_increment", "start_time", "end_time",
        "status", "current_price", "current_bidder", "winner", "final_price",
        "view_count", "extension_count", "settled_at", "created_at", "updated_at",
    )

    def has_add_permission(self, request):
        # Auction creation must go through AuctionForm and its cross-field checks.
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting an auction cascades to its proxy bids; that would silently
        # erase active reserves without refunding participants.
        return False


@admin.register(ProxyBid)
class ProxyBidAdmin(admin.ModelAdmin):
    list_display = ("auction", "bidder", "max_amount", "reserved_amount", "active", "priority_at")
    list_filter = ("active",)
    search_fields = ("auction__title", "bidder__username")
    readonly_fields = ("auction", "bidder", "max_amount", "reserved_amount", "active", "priority_at", "updated_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("auction", "bidder", "displayed_amount", "max_amount", "created_at")
    list_filter = ("created_at",)
    search_fields = ("auction__title", "bidder__username")
    readonly_fields = ("auction", "bidder", "max_amount", "displayed_amount", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "amount", "balance_after", "auction")
    list_filter = ("kind",)
    search_fields = ("user__username", "note")
    readonly_fields = ("user", "auction", "bid", "kind", "amount", "balance_after", "note", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ("user", "auction", "created_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "is_read", "created_at")
    list_filter = ("is_read",)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("auction", "reporter", "reason", "resolved", "created_at")
    list_filter = ("resolved", "reason")
    search_fields = ("auction__title", "reporter__username", "details")


# A user deletion cascades to auctions, proxy bids and ledger rows. That can
# destroy active reserve accounting, so account deletion must be handled by a
# deliberate data-retention workflow rather than the default admin action.
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


@admin.register(User)
class ProtectedUserAdmin(UserAdmin):
    def has_delete_permission(self, request, obj=None):
        return False
