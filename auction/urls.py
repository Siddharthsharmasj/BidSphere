from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register_view, name="register"),
    path("auctions/", views.auction_list, name="auction_list"),
    path("auctions/create/", views.create_auction, name="create_auction"),
    path("auctions/<int:pk>/", views.auction_detail, name="auction_detail"),
    path("auctions/<int:pk>/bid/", views.place_bid, name="place_bid"),
    path("auctions/<int:pk>/watchlist/", views.toggle_watchlist, name="toggle_watchlist"),
    path("auctions/<int:pk>/close/", views.close_my_auction, name="close_my_auction"),
    path("auctions/<int:pk>/cancel/", views.cancel_my_auction, name="cancel_my_auction"),
    path("auctions/<int:pk>/status/", views.auction_status, name="auction_status"),
    path("auctions/<int:pk>/report/", views.report_auction, name="report_auction"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("wallet/", views.wallet, name="wallet"),
    path("my-auctions/", views.my_auctions, name="my_auctions"),
    path("my-bids/", views.my_bids, name="my_bids"),
    path("watchlist/", views.watchlist, name="watchlist"),
    path("profile/", views.profile_view, name="profile"),
    path("notifications/", views.notification_center, name="notifications"),
    path("notifications/read/", views.mark_notifications_read, name="mark_notifications_read"),
    path("seller/analytics/", views.seller_analytics, name="seller_analytics"),
    path("internal/cron/close-expired/", views.cron_close_expired, name="cron_close_expired"),
    path("api/auctions/", views.api_auctions, name="api_auctions"),
    path("api/auctions/<int:pk>/bids/", views.api_bids, name="api_bids"),
]
