"""Tests for the TradingAccount and ReminderHistory models."""

from datetime import timedelta

import pytest
from django.utils import timezone

from trades.models import ReminderSchedule, TradingAccount


@pytest.mark.django_db
def test_days_remaining_right_after_trade(user):
    """Just after a trade there are 30 days remaining."""
    account = TradingAccount.objects.create(
        user=user,
        account_name="Fresh",
        last_trade_date=timezone.now(),
    )
    assert account.days_remaining == 30


@pytest.mark.django_db
def test_days_remaining_after_10_days(user):
    """10 days after the last trade, 20 days remain."""
    account = TradingAccount.objects.create(
        user=user,
        account_name="Midway",
        last_trade_date=timezone.now() - timedelta(days=10),
    )
    assert account.days_remaining == 20


@pytest.mark.django_db
def test_days_remaining_after_30_days_is_zero(user):
    """At exactly 30 days, nothing remains (account is inactive)."""
    account = TradingAccount.objects.create(
        user=user,
        account_name="Boundary",
        last_trade_date=timezone.now() - timedelta(days=30),
    )
    assert account.days_remaining == 0


@pytest.mark.django_db
def test_days_remaining_never_negative(user):
    """days_remaining is clamped to zero, never negative."""
    account = TradingAccount.objects.create(
        user=user,
        account_name="Overdue",
        last_trade_date=timezone.now() - timedelta(days=45),
    )
    assert account.days_remaining == 0


@pytest.mark.django_db
def test_deadline_is_last_trade_plus_30_days(user):
    """The deadline equals last_trade_date + 30 days."""
    last_trade = timezone.now() - timedelta(days=5)
    account = TradingAccount.objects.create(
        user=user,
        account_name="Deadline",
        last_trade_date=last_trade,
    )
    expected = last_trade + timedelta(days=30)
    # Compare with small tolerance to avoid microsecond flakiness.
    diff = abs((account.deadline - expected).total_seconds())
    assert diff < 1


@pytest.mark.django_db
def test_is_inactive_flags_account(user):
    """is_inactive is True once 30 days have passed."""
    fresh = TradingAccount.objects.create(
        user=user, account_name="Fresh", last_trade_date=timezone.now()
    )
    stale = TradingAccount.objects.create(
        user=user,
        account_name="Stale",
        last_trade_date=timezone.now() - timedelta(days=31),
    )
    assert fresh.is_inactive is False
    assert stale.is_inactive is True


@pytest.mark.django_db
def test_account_list_ordered_by_name(user):
    """Accounts are ordered alphabetically by name by default."""
    TradingAccount.objects.create(
        user=user, account_name="Beta", last_trade_date=timezone.now()
    )
    TradingAccount.objects.create(
        user=user, account_name="Alpha", last_trade_date=timezone.now()
    )
    names = list(TradingAccount.objects.values_list("account_name", flat=True))
    assert names == ["Alpha", "Beta"]


@pytest.mark.django_db
def test_next_reminder_is_next_schedule_day_after_recent_trade(user, settings):
    """A fresh account's next reminder is the first schedule day (e.g. 10)."""
    settings.REMINDER_SEND_HOURS = [9, 14]
    ReminderSchedule.objects.create(day_list=[10, 15])
    account = TradingAccount.objects.create(
        user=user, account_name="Fresh", last_trade_date=timezone.now()
    )
    nxt = account.next_reminder_datetime()
    assert nxt is not None
    # days_since==0, so next schedule day is 10 days out at the first hour (9).
    tz = user.get_timezone()
    nxt_local = nxt.astimezone(tz)
    assert nxt_local.hour == 9
    delta_days = (nxt_local.date() - timezone.localtime(timezone.now(), tz).date()).days
    assert delta_days == 10


@pytest.mark.django_db
def test_next_reminder_none_when_inactive(user, settings):
    """No upcoming reminder once the account is past the schedule / inactive."""
    settings.REMINDER_SEND_HOURS = [9, 14]
    ReminderSchedule.objects.create(day_list=[10, 15])
    account = TradingAccount.objects.create(
        user=user,
        account_name="Inactive",
        last_trade_date=timezone.now() - timedelta(days=60),
    )
    assert account.time_until_next_reminder is None
    assert account.next_reminder_label == "No upcoming reminder"


@pytest.mark.django_db
def test_next_reminder_label_not_empty_for_fresh(user, settings):
    """A fresh account yields a non-empty human-friendly label."""
    settings.REMINDER_SEND_HOURS = [9, 14]
    ReminderSchedule.objects.create(day_list=[10, 15])
    account = TradingAccount.objects.create(
        user=user, account_name="Fresh", last_trade_date=timezone.now()
    )
    assert account.next_reminder_label != "No upcoming reminder"
    assert "In " in account.next_reminder_label or "Today" in account.next_reminder_label
