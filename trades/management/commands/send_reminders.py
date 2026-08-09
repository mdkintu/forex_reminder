"""Run due inactivity reminders directly, without Celery.

On shared hosting (cPanel/Passenger) there is no long-running Celery worker or
Redis, so this command does the work of ``check_and_send_reminders`` in the
foreground. Wire it to a cPanel cron job instead of Celery beat, e.g.:

    cd /home/USER/fair && ../virtualenv/bin/python manage.py send_reminders

This keeps the exact same reminder logic (the Celery task is called directly),
so behaviour is identical to the worker path.
"""

from django.core.management.base import BaseCommand

from trades.tasks import check_and_send_reminders


class Command(BaseCommand):
    help = (
        "Run due inactivity reminders now (no Celery). Useful on shared "
        "hosting where background workers are unavailable; schedule via cPanel "
        "cron."
    )

    def handle(self, *args, **options):
        self.stdout.write("Checking and sending due reminders...")
        sent = check_and_send_reminders()
        self.stdout.write(
            self.style.SUCCESS(f"Done. Reminders sent: {sent}")
        )
