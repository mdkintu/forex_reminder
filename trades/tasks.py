import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ReminderHistory, ReminderSchedule, TradingAccount
from .notifications import send_telegram_message, send_whatsapp_message

logger = logging.getLogger(__name__)


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
    subject = f"Inactivity reminder: {account.account_name}"
    message = (
        f"Hello,\n\n"
        f"Your trading account '{account.account_name}' "
        f"(broker: {account.broker or 'unknown'}) has had no trade for "
        f"{day_number} days.\n\n"
        f"Last trade was on {account.last_trade_date:%Y-%m-%d %H:%M}.\n\n"
        f"Please place a trade to keep the account active, or contact your broker.\n\n"
        f"— Forex Account Inactivity Reminder (FAIR)"
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [account.user.email])


def _send_whatsapp(account, day_number) -> None:
    """Send the inactivity reminder via WhatsApp to the user's phone number."""
    body = (
        f"⚠️ Inactivity reminder: account '{account.account_name}' "
        f"(broker: {account.broker or 'unknown'}) has had no trade for "
        f"{day_number} days. Please place a trade to keep it active."
    )
    send_whatsapp_message(account.user.phone_number, body)


def _send_telegram(account, day_number) -> None:
    """Send the inactivity reminder via Telegram to the user's chat id."""
    text = (
        f"⚠️ Inactivity reminder: account '{account.account_name}' "
        f"(broker: {account.broker or 'unknown'}) has had no trade for "
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


# ============================================================================
# The background task
# ============================================================================


@shared_task
def check_and_send_reminders() -> int:
    """Check all trading accounts and send due inactivity reminders.

    Reminder day numbers are read from the global :class:`ReminderSchedule`,
    so the user can configure them interactively (multiple values) via the
    ``set_reminder_days`` management command.

    For each account whose days-since-last-trade is in the schedule, a
    reminder is sent on every enabled channel (unless one was already sent
    for that account+day+channel).

    Returns the number of reminders sent.
    """
    now = timezone.now()
    sent_count = 0
    reminder_days = ReminderSchedule.get().days()

    for account in TradingAccount.objects.select_related("user").all():
        days_since = (now - account.last_trade_date).days

        if days_since not in reminder_days:
            continue

        for channel in ReminderHistory.Channel.values:  # email, whatsapp, telegram
            if not _channel_is_enabled(account, channel):
                continue

            already_sent = ReminderHistory.objects.filter(
                account=account,
                day_number=days_since,
                channel=channel,
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
                    )
                    SENDERS[channel](account, days_since)

                    history.status = "sent"
                    history.save(update_fields=["status"])
                    sent_count += 1
                    logger.info(
                        "[reminder] Sent '%s' reminder for account '%s' (day %s).",
                        channel,
                        account.account_name,
                        days_since,
                    )
            except IntegrityError:
                # A concurrent worker created the record first — skip it.
                logger.info(
                    "[reminder] Duplicate reminder skipped for account '%s' "
                    "(day %s, channel %s).",
                    account.account_name,
                    days_since,
                    channel,
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
