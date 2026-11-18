import logging
from collections import Counter
from dataclasses import dataclass, field

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ReminderHistory, ReminderRun, ReminderSchedule, TradingAccount
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


def _send_email(account, day_number):
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
    return send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [account.user.email])


def _send_whatsapp(account, day_number):
    """Send the inactivity reminder via WhatsApp to the user's phone number."""
    name = _recipient_name(account)
    body = (
        f"⚠️ Hello {name}, inactivity reminder: account "
        f"'{account.account_name}' (#{account.account_number or 'n/a'}, "
        f"broker: {account.broker or 'unknown'}) has had no trade for "
        f"{day_number} days. Please place a trade to keep it active."
    )
    return send_whatsapp_message(account.user.phone_number, body)


def _send_telegram(account, day_number):
    """Send the inactivity reminder via Telegram to the user's chat id."""
    name = _recipient_name(account)
    text = (
        f"⚠️ Hello {name}, inactivity reminder: account "
        f"'{account.account_name}' (#{account.account_number or 'n/a'}, "
        f"broker: {account.broker or 'unknown'}) has had no trade for "
        f"{day_number} days. Please place a trade to keep it active."
    )
    return send_telegram_message(account.user.telegram_chat_id, text)


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


def _due_slot_hour(local_now, send_hours, grace_hours):
    """The delivery slot (local hour) that is due right now, or None.

    The most recent slot at or before the current local hour is due as long
    as we are still within ``grace_hours`` of it. This lets a delayed or
    missed cron run catch up instead of losing the reminder.
    """
    passed = [h for h in sorted(set(send_hours or [])) if h <= local_now.hour]
    if not passed:
        return None
    slot = max(passed)
    if local_now.hour - slot > max(0, grace_hours):
        return None
    return slot


def _traded_since_last_slot(account, local_hour, send_hours, now=None) -> bool:
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
    now_local = timezone.localtime(now or timezone.now(), tz)
    # Datetime of the previous slot earlier today (user's local time).
    previous_slot_time = now_local.replace(
        hour=previous_hour, minute=0, second=0, microsecond=0
    )
    last_local = timezone.localtime(account.last_trade_date, tz)
    return last_local > previous_slot_time


# ============================================================================
# Deciding whether an account is due
# ============================================================================

#: Reasons returned by :func:`evaluate_account` (also shown by
#: ``send_reminders --dry-run`` and counted in each run's summary).
DUE = "due"
NOT_REMINDER_DAY = "not_reminder_day"
PAST_DEADLINE = "past_deadline"
NO_SLOT_DUE = "no_slot_due"
TRADED_SINCE_SLOT = "traded_since_slot"


@dataclass
class Decision:
    """Whether an account is due a reminder right now, and why (not)."""

    reason: str
    day_number: int
    slot_hour: int | None = None

    @property
    def due(self) -> bool:
        return self.reason == DUE


def evaluate_account(account, reminder_days, send_hours, grace_hours, now=None) -> Decision:
    """Decide whether ``account`` is due a reminder at ``now`` (default: now).

    Pure decision logic, no side effects: used by the real run and by
    ``send_reminders --dry-run``.
    """
    now = now or timezone.now()
    # Days since last trade in the account owner's local timezone.
    days_since = account.days_since_last_trade

    if days_since not in reminder_days:
        return Decision(NOT_REMINDER_DAY, days_since)

    # Never remind about an account that's genuinely past the inactivity
    # threshold. Compared by calendar day (days_since), not the exact
    # deadline instant (last_trade_date + 30 days to the second) — that
    # instant is tied to the original trade's time-of-day and would
    # wrongly hide the day-30 reminder whenever the last trade happened
    # earlier in the day than the configured send hours.
    if days_since > TradingAccount.INACTIVITY_THRESHOLD_DAYS:
        return Decision(PAST_DEADLINE, days_since)

    # The delivery slot that is due now in the owner's local time (the
    # latest slot at or before the current hour, within the grace window).
    local_now = timezone.localtime(now, account.user.get_timezone())
    local_hour = _due_slot_hour(local_now, send_hours, grace_hours)
    if local_hour is None:
        return Decision(NO_SLOT_DUE, days_since)

    # Skip later-in-the-day slots if the user already traded after the
    # previous reminder slot (e.g. skip the 2 PM reminder if they traded
    # after the 9 AM one).
    if _traded_since_last_slot(account, local_hour, send_hours, now=now):
        return Decision(TRADED_SINCE_SLOT, days_since, local_hour)

    return Decision(DUE, days_since, local_hour)


# ============================================================================
# Running the job
# ============================================================================


@dataclass
class RunSummary:
    """What one run of the reminder job did."""

    checked: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    reasons: Counter = field(default_factory=Counter)
    #: (account, Decision) pairs, in processing order (used by --dry-run).
    decisions: list = field(default_factory=list)


def _send_due_reminders(account, decision, summary) -> None:
    """Send ``decision``'s reminder on every enabled channel not yet sent."""
    days_since, local_hour = decision.day_number, decision.slot_hour

    for channel in ReminderHistory.Channel.values:  # email, whatsapp, telegram
        if not _channel_is_enabled(account, channel):
            continue

        already_sent = ReminderHistory.objects.filter(
            account=account,
            cycle_start=account.last_trade_date,
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
                    cycle_start=account.last_trade_date,
                    day_number=days_since,
                    channel=channel,
                    status="pending",
                    slot_hour=local_hour,
                )
                result = SENDERS[channel](account, days_since)

                if not result:
                    # Channel not configured / no recipient: record it as
                    # skipped (so we don't retry every hour) but don't
                    # pretend it was delivered.
                    history.status = "skipped"
                    history.save(update_fields=["status"])
                    summary.skipped += 1
                    logger.warning(
                        "[reminder] Skipped '%s' reminder for account '%s' "
                        "(channel not configured or no recipient).",
                        channel,
                        account.account_name,
                    )
                    continue

                history.status = "sent"
                history.save(update_fields=["status"])
                summary.sent += 1
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
            summary.failed += 1
            logger.exception(
                "[reminder] Failed to send '%s' reminder for account '%s' "
                "(day %s): %s",
                channel,
                account.account_name,
                days_since,
                exc,
            )


def run_reminders(dry_run: bool = False) -> RunSummary:
    """Check every trading account and send the reminders that are due.

    On a scheduled reminder day (days-since-last-trade in the global
    :class:`ReminderSchedule`), the reminder is sent once per enabled channel
    at each configured local delivery hour (settings.REMINDER_SEND_HOURS),
    recording each (account, cycle, day, channel, hour) in
    :class:`ReminderHistory` so the same slot is never sent twice.

    With ``dry_run=True`` nothing is sent or recorded; the returned summary
    just says what would happen for each account. Real runs are logged as a
    :class:`ReminderRun` for monitoring.
    """
    started_at = timezone.now()
    summary = RunSummary()
    reminder_days = ReminderSchedule.get().days()
    send_hours = getattr(settings, "REMINDER_SEND_HOURS", [9, 14])
    grace_hours = getattr(settings, "REMINDER_GRACE_HOURS", 3)

    for account in TradingAccount.objects.select_related("user").all():
        decision = evaluate_account(account, reminder_days, send_hours, grace_hours)
        summary.checked += 1
        summary.reasons[decision.reason] += 1
        summary.decisions.append((account, decision))
        logger.info(
            "[reminder] account %s '%s': day %s -> %s",
            account.pk,
            account.account_name,
            decision.day_number,
            decision.reason,
        )
        if decision.due and not dry_run:
            _send_due_reminders(account, decision, summary)

    if not dry_run:
        ReminderRun.objects.create(
            started_at=started_at,
            finished_at=timezone.now(),
            checked=summary.checked,
            sent=summary.sent,
            skipped=summary.skipped,
            failed=summary.failed,
        )
    logger.info(
        "[reminder] run finished%s: checked %s, sent %s, skipped %s, failed %s.",
        " (dry run)" if dry_run else "",
        summary.checked,
        summary.sent,
        summary.skipped,
        summary.failed,
    )
    return summary


@shared_task
def check_and_send_reminders() -> int:
    """Celery entry point: run the reminder job, return the number sent."""
    return run_reminders().sent
