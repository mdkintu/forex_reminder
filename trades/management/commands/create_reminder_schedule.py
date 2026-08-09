from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, PeriodicTask

#: Name of the periodic task in django-celery-beat's DB.
TASK_NAME = "check_and_send_reminders_daily"
#: The Celery task (as registered by @shared_task in trades/tasks.py).
CELERY_TASK_PATH = "trades.tasks.check_and_send_reminders"


class Command(BaseCommand):
    help = (
        "Create (or update) the django-celery-beat periodic task that runs "
        "'check_and_send_reminders' daily at 09:00 UTC."
    )

    def handle(self, *args, **options):
        # Create/get the crontab schedule: daily at 09:00 UTC.
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
