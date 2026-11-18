"""Phase 1: reminder-run health monitoring.

Covers the per-account decision function, dry runs, the ReminderRun log, the
daily admin report and the external healthcheck ping.
"""

from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

import trades.reporting as reporting
import trades.tasks as tasks
from trades.models import ReminderHistory, ReminderRun, ReminderSchedule, TradingAccount


@pytest.fixture
def mock_notifiers():
    with mock.patch.object(tasks, "send_mail") as send_mail, \
         mock.patch.object(tasks, "send_whatsapp_message") as send_whatsapp, \
         mock.patch.object(tasks, "send_telegram_message") as send_telegram:
        yield {"send_mail": send_mail, "send_whatsapp": send_whatsapp, "send_telegram": send_telegram}


@pytest.fixture(autouse=True)
def send_now(settings):
    """Make the current UTC hour a send slot (the test user is on UTC)."""
    settings.REMINDER_SEND_HOURS = [timezone.now().hour]


def _account(user, days_ago, **kw):
    kw.setdefault("notify_email", True)
    return TradingAccount.objects.create(
        user=user,
        account_name=kw.pop("name", f"Acct {days_ago}"),
        last_trade_date=timezone.now() - timedelta(days=days_ago),
        **kw,
    )


def _at(hour):
    """Today (UTC) at the given hour."""
    return timezone.now().replace(hour=hour, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# evaluate_account: one reason per branch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_evaluate_not_reminder_day(user):
    d = tasks.evaluate_account(_account(user, 5), (10, 15), [9], 3, now=_at(9))
    assert d.reason == tasks.NOT_REMINDER_DAY and not d.due and d.day_number == 5


@pytest.mark.django_db
def test_evaluate_past_deadline(user):
    d = tasks.evaluate_account(_account(user, 35), (10, 35), [9], 3, now=_at(9))
    assert d.reason == tasks.PAST_DEADLINE


@pytest.mark.django_db
def test_evaluate_no_slot_due(user):
    d = tasks.evaluate_account(_account(user, 10), (10,), [9], 3, now=_at(8))
    assert d.reason == tasks.NO_SLOT_DUE


@pytest.mark.django_db
def test_evaluate_traded_since_slot(user):
    account = _account(user, 0)
    account.last_trade_date = _at(10)
    d = tasks.evaluate_account(account, (0,), [9, 14], 3, now=_at(15))
    assert d.reason == tasks.TRADED_SINCE_SLOT


@pytest.mark.django_db
def test_evaluate_due(user):
    d = tasks.evaluate_account(_account(user, 10), (10,), [9, 14], 3, now=_at(15))
    assert d.due and d.reason == tasks.DUE and d.slot_hour == 14 and d.day_number == 10


# ---------------------------------------------------------------------------
# run_reminders / ReminderRun
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dry_run_sends_and_records_nothing(user, mock_notifiers):
    _account(user, 10)
    summary = tasks.run_reminders(dry_run=True)

    assert summary.checked == 1 and summary.sent == 0
    assert summary.reasons[tasks.DUE] == 1
    assert ReminderHistory.objects.count() == 0
    assert ReminderRun.objects.count() == 0
    mock_notifiers["send_mail"].assert_not_called()


@pytest.mark.django_db
def test_run_is_logged(user, mock_notifiers):
    _account(user, 10)
    _account(user, 5)
    summary = tasks.run_reminders()

    run = ReminderRun.objects.get()
    assert (run.checked, run.sent, run.skipped, run.failed) == (2, 1, 0, 0)
    assert run.finished_at >= run.started_at
    assert summary.reasons == {tasks.DUE: 1, tasks.NOT_REMINDER_DAY: 1}


@pytest.mark.django_db
def test_run_counts_failures_and_skips(user, mock_notifiers):
    _account(user, 10, notify_telegram=True)
    mock_notifiers["send_mail"].side_effect = RuntimeError("SMTP down")
    mock_notifiers["send_telegram"].return_value = None  # not configured

    tasks.run_reminders()

    run = ReminderRun.objects.get()
    assert (run.sent, run.skipped, run.failed) == (0, 1, 1)


@pytest.mark.django_db
def test_celery_wrapper_still_returns_sent_count(user, mock_notifiers):
    _account(user, 10)
    assert tasks.check_and_send_reminders() == 1


# ---------------------------------------------------------------------------
# Daily admin report
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_chat(settings):
    settings.ADMIN_TELEGRAM_CHAT_ID = "111"
    settings.ADMIN_REPORT_HOUR = 0
    with mock.patch.object(reporting, "send_telegram_message") as send:
        yield send


@pytest.mark.django_db
def test_report_sent_once_per_day_and_flags_at_risk(user, mock_notifiers, admin_chat):
    ReminderSchedule.objects.create(day_list=[10])
    _account(user, 28, name="Nearly closed")  # 2 days left, nothing delivered
    tasks.run_reminders()

    assert reporting.maybe_send_daily_report() is True
    admin_chat.assert_called_once()
    chat_id, text = admin_chat.call_args.args
    assert chat_id == "111"
    assert "Nearly closed" in text and "2 days left" in text

    assert reporting.maybe_send_daily_report() is False  # already sent today
    assert admin_chat.call_count == 1


@pytest.mark.django_db
def test_report_not_flagged_when_reminder_delivered(user, mock_notifiers, admin_chat):
    ReminderSchedule.objects.create(day_list=[28])
    _account(user, 28, name="Reminded")
    tasks.run_reminders()  # sends the day-28 reminder

    reporting.maybe_send_daily_report()
    text = admin_chat.call_args.args[1]
    assert "Reminded" not in text


@pytest.mark.django_db
def test_report_waits_for_report_hour(user, mock_notifiers, admin_chat, settings):
    settings.ADMIN_REPORT_HOUR = 6
    tasks.run_reminders()
    assert reporting.maybe_send_daily_report(now=_at(5)) is False
    admin_chat.assert_not_called()


@pytest.mark.django_db
def test_report_falls_back_to_admin_email(user, mock_notifiers, settings):
    settings.ADMIN_TELEGRAM_CHAT_ID = ""
    settings.ADMIN_REPORT_HOUR = 0
    settings.ADMINS = [("Admin", "admin@example.com")]
    tasks.run_reminders()

    assert reporting.maybe_send_daily_report() is True
    assert len(mail.outbox) == 1
    assert "admin@example.com" in mail.outbox[0].to


@pytest.mark.django_db
def test_report_failure_is_retried_next_run(user, mock_notifiers, admin_chat):
    tasks.run_reminders()
    admin_chat.side_effect = RuntimeError("Telegram down")
    assert reporting.maybe_send_daily_report() is False
    admin_chat.side_effect = None
    assert reporting.maybe_send_daily_report() is True


# ---------------------------------------------------------------------------
# send_reminders command: dry run output + healthcheck ping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_command_dry_run_prints_reasons(user, mock_notifiers):
    _account(user, 10, name="Due one")
    _account(user, 5, name="Not yet")
    out = StringIO()
    call_command("send_reminders", "--dry-run", stdout=out)

    output = out.getvalue()
    assert "DRY RUN" in output
    assert "Due one" in output and tasks.DUE in output
    assert "Not yet" in output and tasks.NOT_REMINDER_DAY in output
    assert ReminderHistory.objects.count() == 0


@pytest.mark.django_db
def test_command_pings_healthcheck(user, mock_notifiers, settings):
    settings.HEALTHCHECK_PING_URL = "https://hc.example/abc"
    with mock.patch.object(reporting, "urlopen") as urlopen:
        call_command("send_reminders", stdout=StringIO())
    urlopen.assert_called_once()
    assert urlopen.call_args.args[0] == "https://hc.example/abc"


@pytest.mark.django_db
def test_command_skips_ping_when_unset(user, mock_notifiers, settings):
    settings.HEALTHCHECK_PING_URL = ""
    with mock.patch.object(reporting, "urlopen") as urlopen:
        call_command("send_reminders", stdout=StringIO())
    urlopen.assert_not_called()


@pytest.mark.django_db
def test_healthcheck_errors_never_raise(settings):
    settings.HEALTHCHECK_PING_URL = "https://hc.example/abc"
    with mock.patch.object(reporting, "urlopen", side_effect=OSError("no network")):
        assert reporting.ping_healthcheck() is False
