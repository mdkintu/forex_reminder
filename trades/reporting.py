"""Operational monitoring for the reminder job.

* :func:`maybe_send_daily_report` sends the admin a once-a-day summary of the
  job's health (runs, sent / skipped / failed) and, most importantly, lists
  accounts close to their deadline that have had no reminder delivered this
  cycle. That turns a silent failure into a visible one.
* :func:`ping_healthcheck` pings an external dead-man's-switch URL (e.g.
  healthchecks.io) after every run, so a cron that stops running entirely is
  noticed too — the daily report can't report on runs that never happen.

Both are called by the ``send_reminders`` management command and never raise.
"""

import logging
from datetime import timedelta
from urllib.request import urlopen

from django.conf import settings
from django.core.mail import mail_admins
from django.db.models import Sum
from django.utils import timezone

from .models import ReminderHistory, ReminderRun, TradingAccount
from .notifications import send_telegram_message

logger = logging.getLogger(__name__)

#: Accounts with this many days left (or fewer) and no delivered reminder in
#: their current cycle are flagged in the report.
AT_RISK_DAYS_LEFT = 3

#: Cap on how many at-risk accounts the report lists individually.
AT_RISK_LIST_LIMIT = 15


def at_risk_accounts():
    """Accounts near their deadline with nothing delivered this cycle.

    Returns ``(account, days_left)`` pairs, most urgent first. Accounts already
    past the deadline are excluded (it's too late to remind them).
    """
    result = []
    for account in TradingAccount.objects.select_related("user"):
        days_since = account.days_since_last_trade
        if days_since > account.inactivity_days:
            continue
        days_left = account.days_remaining
        if days_left > AT_RISK_DAYS_LEFT:
            continue
        delivered = ReminderHistory.objects.filter(
            account=account,
            cycle_start=account.last_trade_date,
            status="sent",
        ).exists()
        if not delivered:
            result.append((account, days_left))
    result.sort(key=lambda pair: pair[1])
    return result


def build_daily_report(now=None) -> str:
    """The plain-text body of the daily admin report."""
    now = now or timezone.now()
    since = now - timedelta(hours=24)
    runs = ReminderRun.objects.filter(finished_at__gte=since)
    totals = runs.aggregate(sent=Sum("sent"), skipped=Sum("skipped"), failed=Sum("failed"))
    run_count = runs.count()
    last_run = ReminderRun.objects.first()  # ordered newest first

    lines = [
        f"FAIR daily report — {now:%Y-%m-%d %H:%M} UTC",
        "",
        f"Runs in the last 24h: {run_count} (expected ~24 with an hourly cron)",
        f"Reminders sent: {totals['sent'] or 0}, skipped: {totals['skipped'] or 0}, "
        f"failed: {totals['failed'] or 0}",
    ]
    if last_run:
        lines.append(f"Last run: {last_run.finished_at:%Y-%m-%d %H:%M} UTC, checked {last_run.checked} accounts")
    if totals["failed"]:
        lines.append("⚠️ Some reminders failed — check reminders.log for the errors.")

    risky = at_risk_accounts()
    lines.append("")
    if risky:
        lines.append(
            f"⚠️ {len(risky)} account(s) within {AT_RISK_DAYS_LEFT} days of their "
            "deadline with NO reminder delivered this cycle:"
        )
        for account, days_left in risky[:AT_RISK_LIST_LIMIT]:
            plural = "day" if days_left == 1 else "days"
            lines.append(
                f"  • {account.account_name} ({account.user.email}) — "
                f"{days_left} {plural} left"
            )
        if len(risky) > AT_RISK_LIST_LIMIT:
            lines.append(f"  … and {len(risky) - AT_RISK_LIST_LIMIT} more")
    else:
        lines.append("✅ No account near its deadline is missing a reminder.")
    return "\n".join(lines)


def maybe_send_daily_report(now=None) -> bool:
    """Send the daily admin report if it's due. Returns True if it was sent.

    Due once per UTC day, on the first run at or after
    ``settings.ADMIN_REPORT_HOUR``. Sent to ``ADMIN_TELEGRAM_CHAT_ID`` when set,
    otherwise emailed to ``ADMINS``. If sending fails, nothing is marked, so
    the next hourly run tries again.
    """
    now = now or timezone.now()
    if now.hour < getattr(settings, "ADMIN_REPORT_HOUR", 6):
        return False

    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if ReminderRun.objects.filter(report_sent=True, finished_at__gte=start_of_day).exists():
        return False

    last_run = ReminderRun.objects.first()
    if last_run is None:
        return False  # nothing to report on (and nowhere to mark it sent)

    chat_id = getattr(settings, "ADMIN_TELEGRAM_CHAT_ID", "")
    if not chat_id and not getattr(settings, "ADMINS", None):
        logger.warning(
            "[report] No ADMIN_TELEGRAM_CHAT_ID or ADMINS configured; "
            "daily report not sent."
        )
        return False

    text = build_daily_report(now)
    try:
        if chat_id:
            if not send_telegram_message(chat_id, text):
                raise RuntimeError("Telegram not configured (TELEGRAM_BOT_TOKEN)")
        else:
            mail_admins("FAIR daily report", text, fail_silently=False)
    except Exception:  # noqa: BLE001 - monitoring must never break the job
        logger.exception("[report] Failed to send the daily report; will retry next run.")
        return False

    last_run.report_sent = True
    last_run.save(update_fields=["report_sent"])
    logger.info("[report] Daily report sent.")
    return True


def ping_healthcheck(failed: bool = False) -> bool:
    """Ping ``settings.HEALTHCHECK_PING_URL`` (if set). Never raises.

    With ``failed=True`` the ``/fail`` endpoint is used (the healthchecks.io
    convention), which alerts immediately instead of waiting for a timeout.
    """
    url = getattr(settings, "HEALTHCHECK_PING_URL", "")
    if not url:
        return False
    if failed:
        url = url.rstrip("/") + "/fail"
    try:
        with urlopen(url, timeout=10):
            pass
        return True
    except Exception:  # noqa: BLE001
        logger.warning("[healthcheck] Ping to %s failed.", url, exc_info=True)
        return False
