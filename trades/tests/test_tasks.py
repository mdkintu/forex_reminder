"""Tests for the check_and_send_reminders Celery task."""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

import trades.tasks as tasks
from trades.models import ReminderHistory, ReminderSchedule, TradingAccount


@pytest.fixture(autouse=True)
def fixed_send_hour(settings):
    """Make the task act now.

    The task only sends when the local hour matches settings.REMINDER_SEND_HOURS.
    Force the send window to include the current hour so tests exercise the
    sending path regardless of when they run.
    """
    current_hour = timezone.localtime(timezone.now()).hour
    settings.REMINDER_SEND_HOURS = [current_hour]


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


@pytest.mark.django_db
def test_task_gates_on_send_hour(user, schedule, mock_notifiers, settings):
    """The task does nothing outside the configured reminder hours."""
    current_hour = timezone.localtime(timezone.now()).hour
    # Force a send window that does NOT include the current hour.
    settings.REMINDER_SEND_HOURS = [(current_hour + 1) % 24]

    TradingAccount.objects.create(
        user=user,
        account_name="Due",
        last_trade_date=timezone.now() - timedelta(days=10),
        notify_email=True,
    )

    sent = tasks.check_and_send_reminders()

    assert sent == 0
    assert ReminderHistory.objects.count() == 0
    mock_notifiers["send_mail"].assert_not_called()


@pytest.mark.django_db
def test_task_uses_recipient_name_in_email(user, schedule, mock_notifiers):
    """Email body greets the user by their first/last name."""
    user.first_name = "Alice"
    user.last_name = "Smith"
    user.save()
    TradingAccount.objects.create(
        user=user,
        account_name="Due",
        account_number="98765",
        last_trade_date=timezone.now() - timedelta(days=10),
        notify_email=True,
    )

    tasks.check_and_send_reminders()

    subject, body, from_email, to = mock_notifiers["send_mail"].call_args.args
    assert to == [user.email]
    assert "Alice Smith" in body
    assert "98765" in body


@pytest.mark.django_db
def test_task_uses_email_when_no_name(user, schedule, mock_notifiers):
    """Email greets with the email when no name is saved."""
    user.first_name = ""
    user.last_name = ""
    user.save()
    TradingAccount.objects.create(
        user=user,
        account_name="Due",
        last_trade_date=timezone.now() - timedelta(days=10),
        notify_email=True,
    )

    tasks.check_and_send_reminders()

    subject, body, from_email, to = mock_notifiers["send_mail"].call_args.args
    assert user.email in body


@pytest.mark.django_db
def test_task_skips_later_slot_when_traded_after_morning(
    user, schedule, mock_notifiers, settings
):
    """A later-in-day slot is skipped if the user traded after the morning slot."""
    tz = user.get_timezone()
    now_local = timezone.localtime(timezone.now(), tz)
    morning_hour = now_local.hour - 1  # a morning slot that already passed
    later_hour = now_local.hour         # the current slot
    settings.REMINDER_SEND_HOURS = [morning_hour, later_hour]

    # User last traded AFTER the morning slot today (e.g. 11 AM, morning was 9).
    last_trade = now_local.replace(hour=morning_hour + 1, minute=0, second=0, microsecond=0)
    TradingAccount.objects.create(
        user=user,
        account_name="TradedAt11",
        last_trade_date=last_trade,
        notify_email=True,
    )

    # But days_since must be on the schedule for the task to even try.
    # Force days_since to a schedule day by setting last_trade_date far back is
    # overridden by the traded-after check, so instead mock the property.
    from unittest.mock import patch
    with patch.object(TradingAccount, "days_since_last_trade", new_callable=mock.PropertyMock, return_value=10):
        sent = tasks.check_and_send_reminders()

    # The later slot should be skipped because a trade happened after morning.
    assert sent == 0
    assert ReminderHistory.objects.count() == 0
    mock_notifiers["send_mail"].assert_not_called()
