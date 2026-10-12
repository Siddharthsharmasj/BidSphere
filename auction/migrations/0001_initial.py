from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, unique=True)),
                ("slug", models.SlugField(max_length=90, unique=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bio", models.TextField(blank=True)),
                ("avatar", models.ImageField(blank=True, null=True, upload_to="avatars/")),
                ("available_credits", models.DecimalField(decimal_places=2, default=Decimal("100000.00"), max_digits=14, validators=[MinValueValidator(Decimal("0.00"))])),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="Auction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField()),
                ("image", models.ImageField(blank=True, null=True, upload_to="auctions/")),
                ("starting_price", models.DecimalField(decimal_places=2, max_digits=14, validators=[MinValueValidator(Decimal("0.01"))])),
                ("minimum_increment", models.DecimalField(decimal_places=2, default=Decimal("100.00"), max_digits=14, validators=[MinValueValidator(Decimal("0.01"))])),
                ("current_price", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("start_time", models.DateTimeField()),
                ("end_time", models.DateTimeField()),
                ("status", models.CharField(choices=[("upcoming", "Upcoming"), ("active", "Live"), ("ended", "Ended"), ("cancelled", "Cancelled")], default="upcoming", max_length=20)),
                ("view_count", models.PositiveIntegerField(default=0)),
                ("extension_count", models.PositiveIntegerField(default=0)),
                ("final_price", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("settled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("category", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="auctions", to="auction.category")),
                ("current_bidder", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="leading_auctions", to=settings.AUTH_USER_MODEL)),
                ("seller", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="auctions", to=settings.AUTH_USER_MODEL)),
                ("winner", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="won_auctions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["status", "end_time"], name="auc_status_end_idx"),
                    models.Index(fields=["category", "status"], name="auc_cat_status_idx"),
                    models.Index(fields=["seller", "status"], name="auc_seller_status_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.CharField(max_length=255)),
                ("link", models.CharField(blank=True, max_length=255)),
                ("is_read", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["user", "is_read", "-created_at"], name="notif_user_read_idx")],
            },
        ),
        migrations.CreateModel(
            name="ProxyBid",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("max_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("reserved_amount", models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=14)),
                ("active", models.BooleanField(default=False)),
                ("priority_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("auction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proxy_bids", to="auction.auction")),
                ("bidder", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="proxy_bids", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-max_amount", "priority_at", "id"],
                "constraints": [models.UniqueConstraint(fields=("auction", "bidder"), name="uniq_proxy_auction_bidder")],
                "indexes": [models.Index(fields=["auction", "active", "max_amount"], name="proxy_auc_active_max_idx")],
            },
        ),
        migrations.CreateModel(
            name="Bid",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("max_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("displayed_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("auction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bids", to="auction.auction")),
                ("bidder", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bids", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["auction", "-created_at"], name="bid_auc_created_idx"),
                    models.Index(fields=["bidder", "-created_at"], name="bid_user_created_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Report",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reason", models.CharField(max_length=80)),
                ("details", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved", models.BooleanField(default=False)),
                ("auction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reports", to="auction.auction")),
                ("reporter", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reports", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="WalletTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("initial", "Initial credits"), ("reserve", "Bid reserve"), ("release", "Reserve release"), ("payment", "Winning payment"), ("sale", "Seller proceeds"), ("adjustment", "Admin adjustment")], max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("balance_after", models.DecimalField(decimal_places=2, max_digits=14)),
                ("note", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("auction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="wallet_transactions", to="auction.auction")),
                ("bid", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="wallet_transactions", to="auction.bid")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="wallet_transactions", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [models.Index(fields=["user", "-created_at"], name="wallet_user_created_idx")],
            },
        ),
        migrations.CreateModel(
            name="Watchlist",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("auction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="watchers", to="auction.auction")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="watchlist_items", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("user", "auction"), name="uniq_watch_user_auction")],
            },
        ),
    ]
