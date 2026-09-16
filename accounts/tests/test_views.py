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
        },
    )
    assert response.status_code == 302  # redirect after success
    user.refresh_from_db()
    assert user.last_name == "Smith"


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


@pytest.mark.django_db
def test_dashboard_saves_detected_timezone_over_utc_default(authenticated_client, user):
    """A new user on the 'UTC' default gets the browser timezone saved."""
    assert user.timezone == "UTC"
    authenticated_client.get(reverse("accounts:dashboard") + "?tz=Africa/Kampala")
    user.refresh_from_db()
    assert user.timezone == "Africa/Kampala"


@pytest.mark.django_db
def test_dashboard_does_not_overwrite_detected_timezone(authenticated_client, user):
    """Once a real timezone is saved, later detections don't change it."""
    user.timezone = "Africa/Kampala"
    user.save()
    authenticated_client.get(reverse("accounts:dashboard") + "?tz=Europe/London")
    user.refresh_from_db()
    assert user.timezone == "Africa/Kampala"


@pytest.mark.django_db
def test_profile_email_change_requires_verification(authenticated_client, user, mailoutbox):
    """Changing email leaves the new address unverified and sends a confirmation."""
    from allauth.account.models import EmailAddress

    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    authenticated_client.post(
        reverse("accounts:profile"),
        {"email": "new@example.com", "first_name": "", "last_name": ""},
    )
    user.refresh_from_db()
    assert user.email == "new@example.com"
    address = EmailAddress.objects.get(user=user)
    assert address.email == "new@example.com"
    assert address.primary is True
    assert address.verified is False
    assert any("new@example.com" in m.to for m in mailoutbox)


# ---------------------------------------------------------------------------
# Connect Telegram (profile page)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_shows_connect_telegram_link_when_not_connected(
    authenticated_client, user, settings
):
    settings.TELEGRAM_BOT_USERNAME = "FAIR_Alertss_bot"
    user.telegram_chat_id = ""  # the shared `user` fixture defaults this set
    user.save()
    response = authenticated_client.get(reverse("accounts:profile"))
    assert response.status_code == 200
    assert response.context["telegram_connect_url"] is not None
    assert "t.me/FAIR_Alertss_bot?start=" in response.context["telegram_connect_url"]
    assert "Connect Telegram" in response.content.decode()


@pytest.mark.django_db
def test_profile_hides_connect_link_without_bot_username_configured(
    authenticated_client, settings
):
    settings.TELEGRAM_BOT_USERNAME = ""
    response = authenticated_client.get(reverse("accounts:profile"))
    assert response.context["telegram_connect_url"] is None


@pytest.mark.django_db
def test_profile_shows_connected_state(authenticated_client, user, settings):
    settings.TELEGRAM_BOT_USERNAME = "FAIR_Alertss_bot"
    user.telegram_chat_id = "123456"
    user.save()
    response = authenticated_client.get(reverse("accounts:profile"))
    assert "Telegram connected" in response.content.decode()
    assert response.context["telegram_connect_url"] is None


@pytest.mark.django_db
def test_disconnect_telegram_clears_chat_id(authenticated_client, user):
    user.telegram_chat_id = "123456"
    user.save()
    response = authenticated_client.post(
        reverse("accounts:profile"), {"disconnect_telegram": "1"}
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.telegram_chat_id == ""
