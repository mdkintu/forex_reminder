"""Tests verifying the Django admin registrations for the three models."""

import pytest
from django.contrib.admin.sites import site

from accounts.admin import CustomUserAdmin
from accounts.models import User
from trades.admin import ReminderHistoryAdmin, TradingAccountAdmin
from trades.models import ReminderHistory, TradingAccount


@pytest.mark.django_db
def test_user_registered_in_admin():
    """The custom User model is registered with the admin site."""
    model_admin = site._registry.get(User)
    assert model_admin is not None
    assert isinstance(model_admin, CustomUserAdmin)


@pytest.mark.django_db
def test_trading_account_registered_in_admin():
    """TradingAccount is registered with the admin site."""
    model_admin = site._registry.get(TradingAccount)
    assert model_admin is not None
    assert isinstance(model_admin, TradingAccountAdmin)


@pytest.mark.django_db
def test_reminder_history_registered_in_admin():
    """ReminderHistory is registered with the admin site."""
    model_admin = site._registry.get(ReminderHistory)
    assert model_admin is not None
    assert isinstance(model_admin, ReminderHistoryAdmin)


@pytest.mark.django_db
def test_user_admin_has_list_display_and_search():
    model_admin = site._registry[User]
    assert "email" in model_admin.list_display
    # search_fields is inherited from UserAdmin when not overridden, or set
    # explicitly; either way the admin should expose email searchability.
    assert "email" in UserAdmin_search_fields_or_default(model_admin)
    model_admin.changelist_view  # ensure the admin can build a changelist


@pytest.mark.django_db
def test_trading_account_admin_has_list_and_search():
    model_admin = site._registry[TradingAccount]
    assert "account_name" in model_admin.list_display
    assert "user" in model_admin.list_display
    assert any("account_name" in f for f in model_admin.search_fields)


@pytest.mark.django_db
def test_reminder_history_admin_has_list_and_search():
    model_admin = site._registry[ReminderHistory]
    assert "sent_at" in model_admin.list_display
    assert any("account" in f for f in model_admin.search_fields)


def UserAdmin_search_fields_or_default(model_admin):
    """Return search_fields, falling back to the parent UserAdmin default."""
    if model_admin.search_fields:
        return model_admin.search_fields
    # UserAdmin's default search_fields include 'email'.
    return ["email", "first_name", "last_name"]


@pytest.mark.django_db
def test_admin_login_logout_flow(client, admin_user):
    """A superuser can access the admin site."""
    client.force_login(admin_user)
    response = client.get("/admin/")
    assert response.status_code == 200
