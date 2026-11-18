"""Per-account inactivity limits; reminder days become "days left".

ReminderSchedule.day_list ("days since last trade", for the old fixed 30-day
limit) is converted to days_left = 30 - day before day_list is dropped, so
the live schedule carries over: [10, 15, 20] -> [20, 15, 10]. Existing
accounts get inactivity_days = 30, so their behaviour is unchanged.
"""

import django.core.validators
import trades.daylists
from django.db import migrations, models


def day_list_to_days_left(apps, schema_editor):
    ReminderSchedule = apps.get_model("trades", "ReminderSchedule")
    for schedule in ReminderSchedule.objects.all():
        old = [d for d in (schedule.day_list or []) if isinstance(d, int)]
        # Same conversion as trades.daylists.days_after_to_days_left (inlined:
        # migrations must not depend on code that may change later).
        schedule.days_left = sorted({30 - d for d in old if 0 <= d <= 30}, reverse=True)
        schedule.save(update_fields=["days_left"])


def days_left_to_day_list(apps, schema_editor):
    ReminderSchedule = apps.get_model("trades", "ReminderSchedule")
    for schedule in ReminderSchedule.objects.all():
        schedule.day_list = sorted({30 - d for d in (schedule.days_left or []) if 0 <= d <= 30})
        schedule.save(update_fields=["day_list"])


class Migration(migrations.Migration):

    dependencies = [
        ("trades", "0006_reminderrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="reminderschedule",
            name="days_left",
            field=models.JSONField(
                default=list,
                help_text="Days before the inactivity deadline on which to send reminders (0 = deadline day), e.g. [20, 15, 5, 3, 1, 0].",
                validators=[trades.daylists.validate_reminder_days],
            ),
        ),
        migrations.AddField(
            model_name="tradingaccount",
            name="inactivity_days",
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text="Days without a trade after which your prop firm closes the account.",
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(365),
                ],
            ),
        ),
        migrations.AddField(
            model_name="tradingaccount",
            name="reminder_days_left",
            field=models.JSONField(
                blank=True,
                null=True,
                validators=[trades.daylists.validate_optional_reminder_days],
            ),
        ),
        migrations.RunPython(day_list_to_days_left, days_left_to_day_list),
        migrations.RemoveField(
            model_name="reminderschedule",
            name="day_list",
        ),
    ]
