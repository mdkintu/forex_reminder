"""Tests for user registration and login (django-allauth email-only)."""

import pytest
from django.urls import reverse

from accounts.models import User


@pytest.mark.django_db
def test_signup_url_path_exists(client):
    """The allauth signup URL is wired up in the project."""
    response = client.get(reverse("account_signup"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_user_can_signup_via_allauth(client):
    """POSTing to the allauth signup view creates a user and logs them in."""
    response = client.post(
        reverse("account_signup"),
        {
            "email": "fresh@example.com",
            "password1": "A-very-strong-pass-1",
            "password2": "A-very-strong-pass-1",
        },
    )
    # Successful signup redirects to the configured signup redirect URL.
    assert response.status_code == 302
    user = User.objects.get(email="fresh@example.com")
    assert user.check_password("A-very-strong-pass-1")
    # The new user is logged in.
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_login_requires_email(client, user):
    """Users sign in with their email address (no username)."""
    response = client.post(
        reverse("account_login"),
        {
            "login": user.email,
            "password": "supersecret-pass-123",
        },
    )
    assert response.status_code == 302
    assert int(client.session["_auth_user_id"]) == user.pk


@pytest.mark.django_db
def test_login_with_wrong_password_rejected(client, user):
    """A wrong password is rejected and the user stays logged out."""
    response = client.post(
        reverse("account_login"),
        {
            "login": user.email,
            "password": "wrong-password",
        },
    )
    assert response.status_code == 200  # re-renders the login form
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_login_redirects_to_dashboard(client, user):
    """After a successful login the user lands on the dashboard."""
    response = client.post(
        reverse("account_login"),
        {
            "login": user.email,
            "password": "supersecret-pass-123",
        },
    )
    assert response.status_code == 302
    assert reverse("accounts:dashboard") in response.url


@pytest.mark.django_db
def test_logout_logs_user_out(client, user):
    """Logging out clears the authenticated session."""
    client.force_login(user)
    assert "_auth_user_id" in client.session

    response = client.post(reverse("account_logout"))
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_authenticated_user_can_access_dashboard(client, user):
    """A logged-in user can reach the dashboard."""
    client.force_login(user)
    response = client.get(reverse("accounts:dashboard"))
    assert response.status_code == 200
