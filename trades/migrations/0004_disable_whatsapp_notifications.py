"""WhatsApp reminders aren't wired up to a real provider yet, and the UI no
longer offers the toggle (see trades/forms.py, templates/tradingaccount_*).
Flip any account that already had it enabled back to False, so nothing is
left silently "on" for a channel that never actually sends.
"""

from django.db import migrations


def disable_whatsapp(apps, schema_editor):
    TradingAccount = apps.get_model("trades", "TradingAccount")
    TradingAccount.objects.filter(notify_whatsapp=True).update(notify_whatsapp=False)


class Migration(migrations.Migration):

    dependencies = [
        ("trades", "0003_remove_reminderhistory_unique_reminder_per_account_day_channel_and_more"),
    ]

    operations = [
        migrations.RunPython(disable_whatsapp, migrations.RunPython.noop),
    ]
