"""Register (or remove) this project's Telegram webhook with Telegram's
servers, so the "Connect Telegram" deep-link flow on the profile page works
(see accounts.views.telegram_webhook).

Run this once after deploying, and again any time SITE_DOMAIN,
TELEGRAM_BOT_TOKEN, or TELEGRAM_WEBHOOK_SECRET change:

    python manage.py set_telegram_webhook
    python manage.py set_telegram_webhook --info    # show the current webhook
    python manage.py set_telegram_webhook --delete  # unregister it

Requires HTTPS: Telegram refuses to deliver a webhook to a non-HTTPS URL, so
this only makes sense once SITE_SCHEME/SITE_DOMAIN point at the real
production host (e.g. fair.tergym.com), not the local dev server.
"""

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse


class Command(BaseCommand):
    help = "Register this project's Telegram webhook with Telegram's servers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Remove the currently registered webhook instead of setting one.",
        )
        parser.add_argument(
            "--info",
            action="store_true",
            help="Print Telegram's current webhook info instead of changing anything.",
        )

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set.")

        import telegram  # lazy import, matches trades/notifications.py

        bot = telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN)

        if options["info"]:
            info = asyncio.run(bot.get_webhook_info())
            self.stdout.write(str(info))
            return

        if options["delete"]:
            asyncio.run(bot.delete_webhook())
            self.stdout.write(self.style.SUCCESS("Webhook removed."))
            return

        if not settings.TELEGRAM_WEBHOOK_SECRET:
            raise CommandError(
                "TELEGRAM_WEBHOOK_SECRET is not set. Generate a random secret "
                "(e.g. `python -c \"import secrets; print(secrets.token_urlsafe(32))\"`) "
                "and set it in .env before running this."
            )
        if settings.SITE_SCHEME != "https":
            raise CommandError(
                f"SITE_SCHEME is '{settings.SITE_SCHEME}', but Telegram requires "
                "an HTTPS webhook URL. Set SITE_SCHEME=https (and SITE_DOMAIN to "
                "your real domain) in .env before running this."
            )

        path = reverse("accounts:telegram_webhook")
        url = f"{settings.SITE_SCHEME}://{settings.SITE_DOMAIN}{path}"

        asyncio.run(
            bot.set_webhook(url=url, secret_token=settings.TELEGRAM_WEBHOOK_SECRET)
        )
        self.stdout.write(self.style.SUCCESS(f"Webhook registered: {url}"))
