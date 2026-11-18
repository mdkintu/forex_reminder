"""Scope reminder de-duplication to the inactivity cycle.

Previously a reminder was unique per (account, day, channel, slot) for the
account's whole lifetime, so once e.g. the day-10 reminder had been sent, a
later cycle (after the user traded again) never got its day-10 reminder.

``cycle_start`` records the account's ``last_trade_date`` at send time and is
now part of the unique key. Existing rows that belong to the account's current
cycle (sent after its last trade) are backfilled so they still de-duplicate;
rows from past cycles stay NULL, which never collides in a unique index.

Order: add the new constraint before dropping the old one, so ``account_id``
stays covered by an index throughout (MySQL needs one for the foreign key).
"""

from django.db import migrations, models
from django.db.models import F, OuterRef, Subquery


def backfill_current_cycle(apps, schema_editor):
    ReminderHistory = apps.get_model("trades", "ReminderHistory")
    TradingAccount = apps.get_model("trades", "TradingAccount")
    last_trade = TradingAccount.objects.filter(pk=OuterRef("account_id")).values(
        "last_trade_date"
    )[:1]
    # Only rows sent during the account's current cycle (after its last trade).
    current = ReminderHistory.objects.filter(
        sent_at__gte=F("account__last_trade_date")
    ).values_list("pk", flat=True)
    ReminderHistory.objects.filter(pk__in=list(current)).update(
        cycle_start=Subquery(last_trade)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("trades", "0004_disable_whatsapp_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="reminderhistory",
            name="cycle_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="reminderhistory",
            constraint=models.UniqueConstraint(
                fields=("account", "cycle_start", "day_number", "channel", "slot_hour"),
                name="unique_reminder_per_cycle_day_channel_slot",
            ),
        ),
        migrations.RunPython(backfill_current_cycle, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="reminderhistory",
            name="unique_reminder_per_account_day_channel_slot",
        ),
    ]
