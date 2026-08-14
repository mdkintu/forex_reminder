from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, PeriodicTask

#: Name of the periodic task in django-celery-beat's DB.
TASK_NAME = "check_and_send_reminders_daily"
#: The Celery task (as registered by @shared_task in trades/tasks.py).
CELERY_TASK_PATH = "trades.tasks.check_and_send_reminders"


class Command(BaseCommand):
    help = (
        "DEPRECATED. This project ships with two reminder schedulers and we've "
        "standardized on the cPanel CRON path (the 'send_reminders' command) for "
        "shared hosting, which needs no Redis/Celery worker.\n\n"
        "This command manages a django-celery-beat PeriodicTask, which is ONLY "
        "needed if you later move to Redis + a Celery Beat worker. Do NOT run "
        "it on cPanel alongside the cron, or reminders would fire twice (once "
        "from the cron and once from Beat, which also runs at a fixed 09:00 UTC "
        "rather than the local 9 AM / 2 PM slots). If you do enable Beat later, "
        "update the schedule below to match settings.REMINDER_SEND_HOURS."
    )

    def handle(self, *args, **options):
        # Create/get the crontab schedule: daily at 09:00 UTC.
        # NOTE: This runs daily at 09:00 UTC, which does NOT match the product's
        # local 9 AM / 2 PM slots. Update to match REMINDER_SEND_HOURS + local
        # timezone if you ever adopt Celery Beat as the scheduler.
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="9",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )

        task, created = PeriodicTask.objects.get_or_create(
            name=TASK_NAME,
            defaults={
                "crontab": schedule,
                "task": CELERY_TASK_PATH,
                "enabled": True,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created periodic task '{TASK_NAME}' "
                                   f"→ {CELERY_TASK_PATH} daily at 09:00 UTC.")
            )
        else:
            # Update in case schedule changed since creation.
            task.crontab = schedule
            task.task = CELERY_TASK_PATH
            task.enabled = True
            task.save(update_fields=["crontab", "task", "enabled"])
            self.stdout.write(
                self.style.WARNING(f"Periodic task '{TASK_NAME}' already existed; "
                                   f"updated it to run daily at 09:00 UTC.")
            )
