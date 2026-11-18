"""Phase 4: reliable delivery — failures recorded and retried, missed days
caught up, and a "send me a test reminder" button."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

import trades.tasks as tasks
from trades.models import ReminderHistory, ReminderSchedule, TradingAccount

Status = ReminderHistory.Status


@pytest.fixture(autouse=True)
def send_now(settings):
    settings.REMINDER_SEND_HOURS = [timezone.now().hour]
    settings.REMINDER_MAX_ATTEMPTS = 3
    settings.REMINDER_CATCHUP_DAYS = 2


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def send_mail():
    with mock.patch.object(tasks, "send_mail") as send:
        yield send


def _acct(user, days_ago, **kw):
    return TradingAccount.objects.create(
        user=user,
        account_name=kw.pop("name", "Acct"),
        last_trade_date=timezone.now() - timedelta(days=days_ago),
        notify_email=True,
        **kw,
    )


# --- failures are recorded and retried -------------------------------------


@pytest.mark.django_db
def test_failure_recorded_then_retried(user, send_mail):
    ReminderSchedule.objects.create(days_left=[20])
    _acct(user, 10)
    send_mail.side_effect = OSError("SMTP connection refused")

    summary = tasks.run_reminders()
    row = ReminderHistory.objects.get()
    assert summary.failed == 1 and summary.sent == 0
    assert row.status == Status.FAILED and row.attempts == 1
    assert "SMTP connection refused" in row.error

    send_mail.side_effect = None
    summary = tasks.run_reminders()  # next cron run, same slot
    row.refresh_from_db()
    assert summary.sent == 1
    assert row.status == Status.SENT and row.attempts == 2


@pytest.mark.django_db
def test_attempts_are_capped(user, send_mail):
    ReminderSchedule.objects.create(days_left=[20])
    _acct(user, 10)
    send_mail.side_effect = OSError("down")

    for _ in range(5):
        tasks.run_reminders()

    assert send_mail.call_count == 3
    assert ReminderHistory.objects.get().attempts == 3


@pytest.mark.django_db
def test_in_flight_row_is_not_sent_again(user, send_mail):
    """A row another worker is still sending (pending) is left alone."""
    ReminderSchedule.objects.create(days_left=[20])
    acct = _acct(user, 10)
    ReminderHistory.objects.create(
        account=acct, cycle_start=acct.last_trade_date, day_number=10,
        channel="email", slot_hour=timezone.now().hour, status=Status.PENDING, attempts=1,
    )
    assert tasks.run_reminders().sent == 0
    send_mail.assert_not_called()


@pytest.mark.django_db
def test_skipped_is_final(user, send_mail):
    ReminderSchedule.objects.create(days_left=[20])
    _acct(user, 10, notify_telegram=True)
    with mock.patch.object(tasks, "send_telegram_message", return_value=None) as tg:
        tasks.run_reminders()
        tasks.run_reminders()
    assert tg.call_count == 1
    assert ReminderHistory.objects.get(channel="telegram").status == Status.SKIPPED


# --- catching up a missed reminder day -------------------------------------


@pytest.mark.django_db
def test_missed_day_is_caught_up_once(user, send_mail):
    ReminderSchedule.objects.create(days_left=[20])  # day 10
    acct = _acct(user, 11)  # day 10 passed with nothing sent

    summary = tasks.run_reminders()
    assert summary.sent == 1
    row = ReminderHistory.objects.get()
    assert row.day_number == 10 and row.catch_up
    subject = send_mail.call_args.args[0]
    assert "missed" in subject.lower()
    body = send_mail.call_args.args[1]
    assert "11 days" in body  # message states the real number of days

    assert tasks.run_reminders().sent == 0  # not repeated
    decision = tasks.evaluate_account(acct, acct.reminder_days(), [timezone.now().hour], 3)
    assert decision.reason == tasks.NOT_REMINDER_DAY


@pytest.mark.django_db
def test_no_catch_up_outside_window(user, send_mail):
    ReminderSchedule.objects.create(days_left=[20])
    _acct(user, 13)  # day 10 was 3 days ago; window is 2
    assert tasks.run_reminders().sent == 0


@pytest.mark.django_db
def test_no_catch_up_when_day_was_delivered(user, send_mail):
    ReminderSchedule.objects.create(days_left=[20])
    acct = _acct(user, 11)
    ReminderHistory.objects.create(
        account=acct, cycle_start=acct.last_trade_date, day_number=10,
        channel="email", slot_hour=9, status=Status.SENT, attempts=1,
    )
    assert tasks.run_reminders().sent == 0


@pytest.mark.django_db
def test_no_catch_up_past_deadline(user, send_mail):
    ReminderSchedule.objects.create(days_left=[0])  # day 30
    acct = _acct(user, 31)
    assert tasks.run_reminders().sent == 0
    decision = tasks.evaluate_account(acct, acct.reminder_days(), [timezone.now().hour], 3)
    assert decision.reason == tasks.PAST_DEADLINE


# --- account page shows delivery state ------------------------------------


@pytest.mark.django_db
def test_detail_page_shows_failure(authenticated_client, user):
    acct = _acct(user, 10)
    ReminderHistory.objects.create(
        account=acct, cycle_start=acct.last_trade_date, day_number=10, channel="email",
        slot_hour=9, status=Status.FAILED, attempts=2, error="SMTPAuthenticationError(535)",
    )
    content = authenticated_client.get(reverse("trades:detail", args=[acct.pk])).content
    assert b"failed" in content and b"SMTPAuthenticationError" in content


# --- "Send me a test reminder" ---------------------------------------------


@pytest.fixture
def tg():
    with mock.patch("accounts.views.send_telegram_message") as send:
        yield send


@pytest.mark.django_db
def test_test_reminder_sends_on_each_channel(authenticated_client, user, tg):
    response = authenticated_client.post(reverse("accounts:test_reminder"), follow=True)
    assert response.status_code == 200
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [user.email]
    tg.assert_called_once()
    assert tg.call_args.args[0] == user.telegram_chat_id
    text = response.content.decode()
    assert "Email" in text and "Telegram" in text


@pytest.mark.django_db
def test_test_reminder_reports_channel_error(authenticated_client, tg):
    tg.side_effect = RuntimeError("Forbidden: bot was blocked by the user")
    response = authenticated_client.post(reverse("accounts:test_reminder"), follow=True)
    assert b"bot was blocked by the user" in response.content
    assert len(mail.outbox) == 1  # email still went out


@pytest.mark.django_db
def test_test_reminder_is_rate_limited(authenticated_client, tg):
    authenticated_client.post(reverse("accounts:test_reminder"))
    response = authenticated_client.post(reverse("accounts:test_reminder"), follow=True)
    assert len(mail.outbox) == 1
    assert b"wait" in response.content.lower()


@pytest.mark.django_db
def test_test_reminder_requires_post(authenticated_client):
    assert authenticated_client.get(reverse("accounts:test_reminder")).status_code == 405


@pytest.mark.django_db
def test_dry_run_labels_catch_up(user, send_mail):
    from io import StringIO

    from django.core.management import call_command

    ReminderSchedule.objects.create(days_left=[20])  # day 10
    _acct(user, 11, name="Late one")
    out = StringIO()
    call_command("send_reminders", "--dry-run", stdout=out)
    line = next(l for l in out.getvalue().splitlines() if "Late one" in l)
    assert "day 11" in line and "catch-up of day 10" in line
