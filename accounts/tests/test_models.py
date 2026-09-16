"""Tests for the custom User model's Telegram link-token helpers."""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import User


@pytest.mark.django_db
def test_get_or_create_telegram_link_token_generates_one(user):
    """A user with no token yet gets one generated and saved."""
    assert user.telegram_link_token == ""
    token = user.get_or_create_telegram_link_token()
    assert token
    user.refresh_from_db()
    assert user.telegram_link_token == token
    assert user.telegram_link_token_created_at is not None


@pytest.mark.django_db
def test_get_or_create_telegram_link_token_reuses_valid_token(user):
    """Calling it again before expiry returns the same token, not a new one."""
    first = user.get_or_create_telegram_link_token()
    second = user.get_or_create_telegram_link_token()
    assert first == second


@pytest.mark.django_db
def test_get_or_create_telegram_link_token_regenerates_after_expiry(user):
    """An expired token is replaced with a fresh one."""
    first = user.get_or_create_telegram_link_token()
    user.telegram_link_token_created_at = timezone.now() - timedelta(
        minutes=User.TELEGRAM_LINK_TOKEN_VALID_MINUTES + 1
    )
    user.save(update_fields=["telegram_link_token_created_at"])

    second = user.get_or_create_telegram_link_token()
    assert second != first


@pytest.mark.django_db
def test_resolve_telegram_link_token_finds_valid_token(user):
    token = user.get_or_create_telegram_link_token()
    resolved = User.resolve_telegram_link_token(token)
    assert resolved == user


@pytest.mark.django_db
def test_resolve_telegram_link_token_rejects_unknown_token():
    assert User.resolve_telegram_link_token("not-a-real-token") is None


@pytest.mark.django_db
def test_resolve_telegram_link_token_rejects_empty_token():
    assert User.resolve_telegram_link_token("") is None


@pytest.mark.django_db
def test_resolve_telegram_link_token_rejects_expired_token(user):
    token = user.get_or_create_telegram_link_token()
    user.telegram_link_token_created_at = timezone.now() - timedelta(
        minutes=User.TELEGRAM_LINK_TOKEN_VALID_MINUTES + 1
    )
    user.save(update_fields=["telegram_link_token_created_at"])

    assert User.resolve_telegram_link_token(token) is None


@pytest.mark.django_db
def test_clear_telegram_link_token(user):
    user.get_or_create_telegram_link_token()
    user.clear_telegram_link_token()
    user.refresh_from_db()
    assert user.telegram_link_token == ""
    assert user.telegram_link_token_created_at is None
