"""Shared pytest fixtures for the forex_reminder test suite."""

import pytest
from django.utils import timezone

from accounts.models import User
from trades.models import ReminderSchedule, TradingAccount


@pytest.fixture
def user(db):
    """Create and return a regular (non-staff) user."""
    return User.objects.create_user(
        email="user@example.com",
        password="supersecret-pass-123",
        first_name="Jane",
        last_name="Doe",
        phone_number="+15551234567",
        telegram_chat_id="987654321",
    )


@pytest.fixture
def second_user(db):
    """A second user, useful for object-isolation tests."""
    return User.objects.create_user(
        email="other@example.com",
        password="another-pass-456",
    )


@pytest.fixture
def authenticated_client(client, user):
    """An HTTP client logged in as the default ``user``."""
    client.force_login(user)
    return client


@pytest.fixture
def trading_account(user):
    """A trading account belonging to the default ``user``."""
    return TradingAccount.objects.create(
        user=user,
        account_name="Demo MT4",
        broker="IC Markets",
        last_trade_date=timezone.now() - timezone.timedelta(days=3),
        notify_email=True,
        notify_whatsapp=True,
        notify_telegram=True,
    )


@pytest.fixture(autouse=True)
def reset_reminder_schedule(db):
    """Ensure every test starts with a predictable reminder schedule.

    The task reads the global singleton ReminderSchedule row. Deleting any
    existing rows before each test makes ``ReminderSchedule.get()`` fall back
    to the defaults, so tests are deterministic regardless of local state.
    """
    ReminderSchedule.objects.all().delete()
    yield
