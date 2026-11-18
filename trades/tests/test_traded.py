"""Phase 2: one-tap "I traded" — model, signed email links, dashboard button."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import signing
from django.urls import reverse
from django.utils import timezone

import trades.tasks as tasks
from trades.models import TradingAccount
from trades.tokens import make_traded_token, read_traded_token, traded_url


@pytest.fixture
def old_account(user):
    return TradingAccount.objects.create(
        user=user,
        account_name="Old",
        account_number="80812345",
        last_trade_date=timezone.now() - timedelta(days=20),
    )


@pytest.mark.django_db
def test_mark_traded_resets_countdown(old_account):
    old_account.mark_traded()
    old_account.refresh_from_db()
    assert old_account.days_since_last_trade == 0
    assert timezone.now() - old_account.last_trade_date < timedelta(seconds=5)


# --- signed tokens ---------------------------------------------------------


@pytest.mark.django_db
def test_token_round_trip(old_account):
    assert read_traded_token(make_traded_token(old_account)) == old_account


@pytest.mark.django_db
def test_token_tampered_or_garbage_rejected(old_account):
    token = make_traded_token(old_account)
    assert read_traded_token(token[:-2] + "xx") is None
    assert read_traded_token("garbage") is None


@pytest.mark.django_db
def test_token_expires(old_account):
    token = make_traded_token(old_account)
    later = timezone.now() + timedelta(days=8)
    with mock.patch("django.core.signing.time.time", return_value=later.timestamp()):
        assert read_traded_token(token) is None


@pytest.mark.django_db
def test_token_for_account_moved_to_other_user_rejected(old_account, second_user):
    token = make_traded_token(old_account)
    old_account.user = second_user
    old_account.save()
    assert read_traded_token(token) is None


@pytest.mark.django_db
def test_traded_url_is_absolute(old_account, settings):
    settings.SITE_SCHEME, settings.SITE_DOMAIN = "https", "fair.example.com"
    assert traded_url(old_account).startswith("https://fair.example.com/trades/traded/")


# --- emailed link view (no login) -----------------------------------------


@pytest.mark.django_db
def test_link_get_does_not_change_anything(client, old_account):
    before = old_account.last_trade_date
    url = reverse("trades:traded_link", args=[make_traded_token(old_account)])
    response = client.get(url)

    assert response.status_code == 200
    assert b"Old" in response.content
    old_account.refresh_from_db()
    assert old_account.last_trade_date == before  # scanners pre-fetch GETs


@pytest.mark.django_db
def test_link_post_resets(client, old_account):
    url = reverse("trades:traded_link", args=[make_traded_token(old_account)])
    response = client.post(url)

    assert response.status_code == 200
    old_account.refresh_from_db()
    assert old_account.days_since_last_trade == 0


@pytest.mark.django_db
def test_link_invalid_token_is_friendly(client, old_account):
    before = old_account.last_trade_date
    url = reverse("trades:traded_link", args=["bad-token"])
    assert client.get(url).status_code == 200
    response = client.post(url)
    assert response.status_code == 200
    assert b"expired" in response.content.lower()
    old_account.refresh_from_db()
    assert old_account.last_trade_date == before


# --- dashboard / detail button (login) ------------------------------------


@pytest.mark.django_db
def test_button_resets_own_account(authenticated_client, old_account):
    response = authenticated_client.post(reverse("trades:mark_traded", args=[old_account.pk]))
    assert response.status_code == 302
    old_account.refresh_from_db()
    assert old_account.days_since_last_trade == 0


@pytest.mark.django_db
def test_button_redirects_to_safe_next(authenticated_client, old_account):
    url = reverse("trades:mark_traded", args=[old_account.pk])
    ok = authenticated_client.post(url, {"next": "/dashboard/"})
    assert ok["Location"] == "/dashboard/"
    evil = authenticated_client.post(url, {"next": "https://evil.example/"})
    assert evil["Location"] == reverse("trades:detail", args=[old_account.pk])


@pytest.mark.django_db
def test_button_cannot_touch_others_account(client, second_user, old_account):
    client.force_login(second_user)
    response = client.post(reverse("trades:mark_traded", args=[old_account.pk]))
    assert response.status_code == 404


@pytest.mark.django_db
def test_button_requires_post_and_login(authenticated_client, old_account):
    url = reverse("trades:mark_traded", args=[old_account.pk])
    assert authenticated_client.get(url).status_code == 405
    authenticated_client.logout()
    response = authenticated_client.post(url)  # anonymous now
    assert response.status_code == 302 and "login" in response["Location"]
    old_account.refresh_from_db()
    assert old_account.days_since_last_trade == 20


@pytest.mark.django_db
def test_dashboard_shows_button(authenticated_client, old_account):
    response = authenticated_client.get(reverse("accounts:dashboard"))
    assert reverse("trades:mark_traded", args=[old_account.pk]).encode() in response.content


# --- reminders carry the one-tap actions ----------------------------------


@pytest.mark.django_db
def test_email_reminder_contains_traded_link(old_account):
    with mock.patch.object(tasks, "send_mail") as send_mail:
        tasks._send_email(old_account, 20)
    body = send_mail.call_args.args[1]
    assert "/trades/traded/" in body


@pytest.mark.django_db
def test_telegram_reminder_has_traded_button(old_account):
    with mock.patch.object(tasks, "send_telegram_message") as send:
        tasks._send_telegram(old_account, 20)
    buttons = send.call_args.kwargs["buttons"]
    assert ("✅ I traded", f"traded:{old_account.pk}") in buttons[0]


def test_token_salt_is_scoped():
    """A value signed for another purpose can't be used as a traded token."""
    assert read_traded_token(signing.dumps({"a": 1, "u": 1})) is None
