from django.db import migrations


def seed_categories(apps, schema_editor):
    Category = apps.get_model("auction", "Category")
    categories = [
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
    for name, slug in categories:
        Category.objects.get_or_create(slug=slug, defaults={"name": name})


def unseed_categories(apps, schema_editor):
    Category = apps.get_model("auction", "Category")
    # Preserve seeded categories that now have auctions referencing them.
    # Category.auctions uses PROTECT, so deleting referenced rows would make a
    # migration rollback fail and risk data loss.
    Category.objects.filter(
        slug__in=[
            "electronics", "vehicles", "fashion", "collectibles", "art",
            "home-garden", "books", "sports", "music", "other",
        ],
        auctions__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("auction", "0001_initial")]
    operations = [migrations.RunPython(seed_categories, unseed_categories)]
