import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ReminderHistory, ReminderSchedule, TradingAccount
from .notifications import send_telegram_message, send_whatsapp_message

logger = logging.getLogger(__name__)


def _recipient_name(account):
    """A display name for the reminder recipient.

    Prefers the user's first or last name; falls back to their email if no
    name is saved.
    """
    user = account.user
    if user.first_name or user.last_name:
        return " ".join(n for n in (user.first_name, user.last_name) if n).strip()
    return user.email


# ============================================================================
# Notification senders
# ----------------------------------------------------------------------------
# Each sender builds the reminder text for a given account/channel and hands it
# off to the corresponding helper in ``trades/notifications.py`` (or to
# Django's send_mail), using the user's contact info from the account.
# ============================================================================


def _send_email(account, day_number) -> None:
    """Send the inactivity reminder via email.

    Uses settings.EMAIL_BACKEND (console for dev, SMTP for production).
    """
    name = _recipient_name(account)
    subject = f"Inactivity reminder: {account.account_name}"
    message = (
        f"Hello {name},\n\n"
        f"Your trading account '{account.account_name}' "
        f"(account #: {account.account_number or 'n/a'}, "
        f"broker: {account.broker or 'unknown'}) has had no trade for "
        f"{day_number} days.\n\n"
        f"Last trade was on {account.last_trade_date:%Y-%m-%d %H:%M}.\n\n"
        f"Please place a trade to keep the account active, or contact your broker.\n\n"
        f"— Forex Account Inactivity Reminder (FAIR)"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [account.user.email])


def _send_whatsapp(account, day_number) -> None:
    """Send the inactivity reminder via WhatsApp to the user's phone number."""
    name = _recipient_name(account)
    body = (
        f"⚠️ Hello {name}, inactivity reminder: account "
        f"'{account.account_name}' (#{account.account_number or 'n/a'}, "
        f"broker: {account.broker or 'unknown'}) has had no trade for "
        f"{day_number} days. Please place a trade to keep it active."
    )
    send_whatsapp_message(account.user.phone_number, body)


def _send_telegram(account, day_number) -> None:
    """Send the inactivity reminder via Telegram to the user's chat id."""
    name = _recipient_name(account)
    text = (
        f"⚠️ Hello {name}, inactivity reminder: account "
        f"'{account.account_name}' (#{account.account_number or 'n/a'}, "
        f"broker: {account.broker or 'unknown'}) has had no trade for "
        f"{day_number} days. Please place a trade to keep it active."
    )
    send_telegram_message(account.user.telegram_chat_id, text)


SENDERS = {
    ReminderHistory.Channel.EMAIL: _send_email,
    ReminderHistory.Channel.WHATSAPP: _send_whatsapp,
    ReminderHistory.Channel.TELEGRAM: _send_telegram,
}


def _channel_is_enabled(account, channel) -> bool:
    return {
        ReminderHistory.Channel.EMAIL: account.notify_email,
        ReminderHistory.Channel.WHATSAPP: account.notify_whatsapp,
        ReminderHistory.Channel.TELEGRAM: account.notify_telegram,
    }[channel]


def _traded_since_last_slot(account, local_hour, send_hours) -> bool:
    """True if the user traded after the previous reminder slot today.

    For a later slot in the day (e.g. the 2 PM one), if the user placed a
    trade *after* the previous slot (e.g. the 9 AM one), we skip that later
    reminder — they already reacted. Only the *first* slot of the day is
    never skipped by this check.
    """
    send_hours = sorted(set(send_hours or []))
    if not send_hours or local_hour == send_hours[0]:
        return False  # first slot of the day: nothing before it today

    # The most recent earlier slot that occurred earlier today.
    earlier = [h for h in send_hours if h < local_hour]
    if not earlier:
        return False
    previous_hour = max(earlier)

    tz = account.user.get_timezone()
    now_local = timezone.localtime(timezone.now(), tz)
    # Datetime of the previous slot earlier today (user's local time).
    previous_slot_time = now_local.replace(
        hour=previous_hour, minute=0, second=0, microsecond=0
    )
    last_local = timezone.localtime(account.last_trade_date, tz)
    return last_local > previous_slot_time


# ============================================================================
# The background task
# ============================================================================


@shared_task
def check_and_send_reminders() -> int:
    """Check all trading accounts and send due inactivity reminders.

    On a scheduled reminder day (days-since-last-trade in the global
    :class:`ReminderSchedule`), the reminder is sent once per enabled channel
    at each configured local delivery hour (settings.REMINDER_SEND_HOURS, e.g.
    9 AM and 2 PM). The task is driven by a cron that runs at least as often
    as the smallest interval between those hours; it only sends when the
    account owner's local hour matches a configured delivery hour, recording
    each (account, day, channel, hour) in :class:`ReminderHistory` so the same
    slot is never sent twice.

    Returns the number of reminders sent.
    """
    sent_count = 0
    reminder_days = ReminderSchedule.get().days()
    send_hours = getattr(settings, "REMINDER_SEND_HOURS", [9, 14])

    for account in TradingAccount.objects.select_related("user").all():
        # Days since last trade in the account owner's local timezone.
        days_since = account.days_since_last_trade

        if days_since not in reminder_days:
            continue

        # The account owner's current local wall-clock hour (0-23).
        local_hour = timezone.localtime(timezone.now(), account.user.get_timezone()).hour

        # Only act when we're inside one of the configured delivery windows.
        if local_hour not in send_hours:
            continue

        # Skip later-in-the-day slots if the user already traded after the
        # previous reminder slot (e.g. skip the 2 PM reminder if they traded
        # after the 9 AM one).
        if _traded_since_last_slot(account, local_hour, send_hours):
            continue

        for channel in ReminderHistory.Channel.values:  # email, whatsapp, telegram
            if not _channel_is_enabled(account, channel):
                continue

            already_sent = ReminderHistory.objects.filter(
                account=account,
                day_number=days_since,
                channel=channel,
                slot_hour=local_hour,
            ).exists()
            if already_sent:
                continue

            try:
                with transaction.atomic():
                    history = ReminderHistory.objects.create(
                        account=account,
                        day_number=days_since,
                        channel=channel,
                        status="pending",
                        slot_hour=local_hour,
                    )
                    SENDERS[channel](account, days_since)

                    history.status = "sent"
                    history.save(update_fields=["status"])
                    sent_count += 1
                    logger.info(
                        "[reminder] Sent '%s' reminder for account '%s' (day %s, %02d:00 local).",
                        channel,
                        account.account_name,
                        days_since,
                        local_hour,
                    )
            except IntegrityError:
                # A concurrent worker created the record first — skip it.
                logger.info(
                    "[reminder] Duplicate reminder skipped for account '%s' "
                    "(day %s, channel %s, hour %s).",
                    account.account_name,
                    days_since,
                    channel,
                    local_hour,
                )
            except Exception as exc:  # noqa: BLE001 - log and continue
                logger.exception(
                    "[reminder] Failed to send '%s' reminder for account '%s' "
                    "(day %s): %s",
                    channel,
                    account.account_name,
                    days_since,
                    exc,
                )

    logger.info("[reminder] check_and_send_reminders finished. Sent %s.", sent_count)
    return sent_count
