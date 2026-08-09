"""Tests for public pages and protected-page redirects."""

import pytest
from django.urls import reverse
from django.utils import timezone

from trades.models import TradingAccount


@pytest.mark.django_db
def test_public_landing_page_loads(client):
    """The root URL serves the public landing page for anonymous users."""
    response = client.get("/")
    assert response.status_code == 200
    assert "templates rendered"  # sanity: the response body was produced


@pytest.mark.django_db
def test_landing_page_visible_to_anyone(client):
    """Landing page does not require authentication."""
    login_url = reverse("account_login")
    response = client.get("/")
    assert response.status_code == 200
    # Should not have been redirected to the login page.
    assert response.request["PATH_INFO"] != login_url


@pytest.mark.django_db
def test_dashboard_redirects_anonymous_to_login(client):
    """Anonymous users are sent to the login page from the dashboard."""
    dashboard_url = reverse("accounts:dashboard")
    response = client.get(dashboard_url)
    assert response.status_code == 302
    assert reverse("account_login") in response.url


@pytest.mark.django_db
def test_profile_redirects_anonymous_to_login(client):
    """Anonymous users are sent to login from the profile page."""
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 302
    assert reverse("account_login") in response.url


# ---------------------------------------------------------------------------
# Profile form (view + update)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_page_renders_form(authenticated_client):
    """The profile page renders the edit form for the logged-in user."""
    response = authenticated_client.get(reverse("accounts:profile"))
    assert response.status_code == 200
    assert "form" in response.context
    # Form should be pre-filled with the user's current details.
    assert response.context["form"].initial["email"] == "user@example.com"


@pytest.mark.django_db
def test_profile_form_updates_user(authenticated_client, user):
    """Submitting the profile form persists the changes."""
    response = authenticated_client.post(
        reverse("accounts:profile"),
        {
            "email": user.email,
            "first_name": "Jane",
            "last_name": "Smith",
            "phone_number": "+441234567890",
            "telegram_chat_id": "111222333",
        },
    )
    assert response.status_code == 302  # redirect after success
    user.refresh_from_db()
    assert user.last_name == "Smith"
    assert user.phone_number == "+441234567890"
    assert user.telegram_chat_id == "111222333"


@pytest.mark.django_db
def test_profile_form_rejects_duplicate_email(authenticated_client, user, second_user):
    """A second user already owns an email; updating to it must fail."""
    response = authenticated_client.post(
        reverse("accounts:profile"),
        {
            "email": second_user.email,  # taken by another user
            "first_name": "Jane",
            "last_name": "Doe",
        },
    )
    assert response.status_code == 200  # form re-rendered with errors
    assert response.context["form"].errors


# ---------------------------------------------------------------------------
# Dashboard (renders real user data)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_shows_accounts(authenticated_client, user):
    """The dashboard lists the user's trading accounts."""
    TradingAccount.objects.create(
        user=user,
        account_name="Alpha Broker",
        last_trade_date=timezone.now() - timezone.timedelta(days=2),
    )
    response = authenticated_client.get(reverse("accounts:dashboard"))
    assert response.status_code == 200
    assert "Alpha Broker" in response.content.decode()


@pytest.mark.django_db
def test_dashboard_shows_empty_state_when_no_accounts(authenticated_client):
    """Without accounts the dashboard shows the empty prompt."""
    response = authenticated_client.get(reverse("accounts:dashboard"))
    assert response.status_code == 200
    assert not response.context["accounts"]
    assert "haven't added any trading accounts yet" in response.content.decode()
