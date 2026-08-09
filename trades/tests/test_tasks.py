"""Tests for the check_and_send_reminders Celery task."""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

import trades.tasks as tasks
from trades.models import ReminderHistory, ReminderSchedule, TradingAccount


@pytest.fixture
def schedule():
    """A reminder schedule with a known, small set of day numbers."""
    return ReminderSchedule.objects.create(day_list=[10, 15])


@pytest.fixture
def mock_notifiers():
    """Patch the notification helpers so the task never hits real services."""
    with mock.patch.object(tasks, "send_mail") as send_mail, \
         mock.patch.object(tasks, "send_whatsapp_message") as send_whatsapp, \
         mock.patch.object(tasks, "send_telegram_message") as send_telegram:
        yield {
            "send_mail": send_mail,
            "send_whatsapp": send_whatsapp,
            "send_telegram": send_telegram,
        }


@pytest.mark.django_db
def test_task_sends_due_reminders(user, schedule, mock_notifiers):
    """Accounts due on a schedule day get a reminder per enabled channel."""
    # 10 days since last trade -> falls on schedule day 10.
    TradingAccount.objects.create(
        user=user,
        account_name="Due",
        last_trade_date=timezone.now() - timedelta(days=10),
        notify_email=True,
        notify_whatsapp=True,
        notify_telegram=True,
    )

    sent = tasks.check_and_send_reminders()

    # 3 channels enabled => 3 reminders sent.
    assert sent == 3
    assert ReminderHistory.objects.filter(account__account_name="Due").count() == 3

    # Each enabled channel was called, email with the correct recipient.
    mock_notifiers["send_mail"].assert_called_once()
    mock_notifiers["send_whatsapp"].assert_called_once()
    mock_notifiers["send_telegram"].assert_called_once()
    mock_notifiers["send_mail"].assert_called_once_with(
        mock.ANY, mock.ANY, mock.ANY, [user.email]
    )

    # Every record is marked as 'sent'.
    assert list(
        ReminderHistory.objects.values_list("status", flat=True)
    ) == ["sent", "sent", "sent"]


@pytest.mark.django_db
def test_task_skips_accounts_not_on_schedule(user, schedule, mock_notifiers):
    """Accounts whose days-since-trade is not in the schedule are skipped."""
    TradingAccount.objects.create(
        user=user,
        account_name="Not due yet",
        last_trade_date=timezone.now() - timedelta(days=5),  # not in [10, 15]
        notify_email=True,
    )

    sent = tasks.check_and_send_reminders()

    assert sent == 0
    assert ReminderHistory.objects.count() == 0
    mock_notifiers["send_mail"].assert_not_called()


@pytest.mark.django_db
def test_task_honors_channel_preferences(user, schedule, mock_notifiers):
    """Only channels that are enabled for the account are sent."""
    TradingAccount.objects.create(
        user=user,
        account_name="Email only",
        last_trade_date=timezone.now() - timedelta(days=10),
        notify_email=True,
        notify_whatsapp=False,
        notify_telegram=False,
    )

    sent = tasks.check_and_send_reminders()

    assert sent == 1
    history = ReminderHistory.objects.get()
    assert history.channel == ReminderHistory.Channel.EMAIL
    mock_notifiers["send_mail"].assert_called_once()
    mock_notifiers["send_whatsapp"].assert_not_called()
    mock_notifiers["send_telegram"].assert_not_called()


@pytest.mark.django_db
def test_task_avoids_duplicates(user, schedule, mock_notifiers):
    """Running the task twice does not send duplicate reminders."""
    TradingAccount.objects.create(
        user=user,
        account_name="Dupe candidate",
        last_trade_date=timezone.now() - timedelta(days=10),
        notify_email=True,
        notify_whatsapp=True,
        notify_telegram=True,
    )

    first = tasks.check_and_send_reminders()
    second = tasks.check_and_send_reminders()

    assert first == 3
    assert second == 0  # nothing new sent on the second pass
    # Only one history row per account+day+channel.
    assert ReminderHistory.objects.count() == 3


@pytest.mark.django_db
def test_task_sends_for_multiple_different_dates(user, schedule, mock_notifiers):
    """Accounts with different last_trade_dates are handled correctly."""
    TradingAccount.objects.create(
        user=user,
        account_name="Day 10",
        last_trade_date=timezone.now() - timedelta(days=10),
        notify_email=True,
    )
    TradingAccount.objects.create(
        user=user,
        account_name="Day 15",
        last_trade_date=timezone.now() - timedelta(days=15),
        notify_email=True,
    )

    sent = tasks.check_and_send_reminders()

    assert sent == 2
    assert ReminderHistory.objects.count() == 2
    day_numbers = set(ReminderHistory.objects.values_list("day_number", flat=True))
    assert day_numbers == {10, 15}


@pytest.mark.django_db
def test_task_records_the_correct_day_number(user, schedule, mock_notifiers):
    """ReminderHistory.day_number reflects the days since last trade."""
    TradingAccount.objects.create(
        user=user,
        account_name="Fifteen",
        last_trade_date=timezone.now() - timedelta(days=15),
        notify_email=True,
    )

    tasks.check_and_send_reminders()

    history = ReminderHistory.objects.get()
    assert history.day_number == 15


@pytest.mark.django_db
def test_task_no_reminders_when_no_due_accounts(user, schedule, mock_notifiers):
    """With no matching accounts the task returns 0 and creates nothing."""
    TradingAccount.objects.create(
        user=user,
        account_name="Safe",
        last_trade_date=timezone.now(),  # 0 days -> not on schedule
        notify_email=True,
    )

    sent = tasks.check_and_send_reminders()

    assert sent == 0
    assert ReminderHistory.objects.count() == 0
