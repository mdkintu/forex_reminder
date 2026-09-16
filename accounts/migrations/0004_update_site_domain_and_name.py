"""Point django.contrib.sites' default Site row at this project.

Without this, Site 1 keeps its "example.com" placeholder domain/name, which
allauth uses verbatim in every confirmation/verification email ("Hello from
example.com!" with a link to example.com). Reads settings.SITE_DOMAIN /
SITE_NAME so it reflects whatever .env sets for the current environment.
"""

from django.conf import settings
from django.db import migrations


def set_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={
            "domain": settings.SITE_DOMAIN,
            "name": settings.SITE_NAME,
        },
    )


def revert_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(id=settings.SITE_ID).update(
        domain="example.com", name="example.com"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_user_timezone"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(set_site, revert_site),
    ]
