import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("auction", "0002_seed_categories"),
    ]

    operations = [
        migrations.AlterField(
            model_name="proxybid",
            name="priority_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
