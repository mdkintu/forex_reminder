"""Run due inactivity reminders directly, without Celery.

On shared hosting (cPanel/Passenger) there is no long-running Celery worker or
Redis, so this command does the work in the foreground. Wire it to an hourly
cPanel cron job, e.g.:

    cd /home/USER/fair && ../virtualenv/bin/python manage.py send_reminders >> reminders.log 2>&1

After each run it also sends the once-a-day admin report (when due) and pings
the external healthcheck URL (when configured).

Use ``--dry-run`` to see, for every account, whether it is due a reminder
right now and why (not) — without sending or recording anything.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from trades import reporting
from trades.tasks import run_reminders


class Command(BaseCommand):
    help = (
        "Run due inactivity reminders now (no Celery). Schedule hourly via "
        "cron. --dry-run shows what would happen without sending."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show each account's status and reason; send and record nothing.",
        )

    def handle(self, *args, **options):
        if options["dry_run"]:
            self._dry_run()
            return

        self.stdout.write(f"[{timezone.now():%Y-%m-%d %H:%M:%S} UTC] Checking and sending due reminders...")
        try:
            summary = run_reminders()
        except Exception:
            reporting.ping_healthcheck(failed=True)
            raise

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Reminders sent: {summary.sent} "
                f"(checked {summary.checked}, skipped {summary.skipped}, "
                f"failed {summary.failed}; {self._reasons(summary)})"
            )
        )
        if reporting.maybe_send_daily_report():
            self.stdout.write("Daily admin report sent.")
        reporting.ping_healthcheck()

    def _dry_run(self):
        summary = run_reminders(dry_run=True)
        self.stdout.write(self.style.WARNING("DRY RUN — nothing is sent or recorded."))
        for account, decision in summary.decisions:
            nxt = account.next_reminder_datetime()
            nxt_label = nxt.strftime("%Y-%m-%d %H:%M %Z") if nxt else "none"
            slot = f" at {decision.slot_hour:02d}:00" if decision.slot_hour is not None else ""
            catch_up = f" (catch-up of day {decision.day_number})" if decision.catch_up else ""
            self.stdout.write(
                f"  #{account.pk} {account.account_name!r} ({account.user.email}, "
                f"{account.user.timezone}): day {account.days_since_last_trade}, "
                f"{account.days_remaining} left -> {decision.reason}{catch_up}{slot} | next: {nxt_label}"
            )
        self.stdout.write(f"Checked {summary.checked}: {self._reasons(summary)}")

    @staticmethod
    def _reasons(summary):
        return ", ".join(f"{k}={v}" for k, v in sorted(summary.reasons.items())) or "no accounts"
