from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, WalletTransaction


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if not created:
        return
    profile = Profile.objects.create(user=instance, available_credits=Decimal("100000.00"))
    WalletTransaction.objects.create(
        user=instance,
        kind=WalletTransaction.Kind.INITIAL,
        amount=Decimal("100000.00"),
        balance_after=profile.available_credits,
        note="Demo virtual-credit account opening balance",
    )
