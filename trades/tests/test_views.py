"""Tests for TradingAccount CRUD views (create, read, update, delete)."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from trades.models import TradingAccount

LIST_URL = reverse("trades:list")


def _add_url():
    return reverse("trades:add")


def _detail_url(pk):
    return reverse("trades:detail", kwargs={"pk": pk})


def _edit_url(pk):
    return reverse("trades:edit", kwargs={"pk": pk})


def _delete_url(pk):
    return reverse("trades:delete", kwargs={"pk": pk})


# ---------------------------------------------------------------------------
# Anonymous access is forbidden
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_redirects_anonymous(client):
    response = client.get(LIST_URL)
    assert response.status_code == 302
    assert reverse("account_login") in response.url


@pytest.mark.django_db
def test_add_page_redirects_anonymous(client):
    response = client.get(_add_url())
    assert response.status_code == 302


@pytest.mark.django_db
def test_detail_redirects_anonymous(client, trading_account):
    response = client.get(_detail_url(trading_account.pk))
    assert response.status_code == 302


@pytest.mark.django_db
def test_edit_redirects_anonymous(client, trading_account):
    response = client.get(_edit_url(trading_account.pk))
    assert response.status_code == 302


@pytest.mark.django_db
def test_delete_redirects_anonymous(client, trading_account):
    response = client.get(_delete_url(trading_account.pk))
    assert response.status_code == 302


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_account(authenticated_client):
    response = authenticated_client.post(
        _add_url(),
        {
            "account_name": "New Account",
            "broker": "Pepperstone",
            "last_trade_date": "2025-01-01T10:00",
            "notify_email": "on",
        },
    )
    assert response.status_code == 302
    assert response.url == LIST_URL

    account = TradingAccount.objects.get(account_name="New Account")
    assert account.broker == "Pepperstone"


@pytest.mark.django_db
def test_get_create_page_uses_model_form(authenticated_client):
    response = authenticated_client.get(_add_url())
    assert response.status_code == 200
    assert "form" in response.context


# ---------------------------------------------------------------------------
# Read (list + detail)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_list_shows_own_accounts_only(authenticated_client, user, second_user):
    mine = TradingAccount.objects.create(
        user=user, account_name="Mine", last_trade_date=timezone.now()
    )
    TradingAccount.objects.create(
        user=second_user, account_name="Theirs", last_trade_date=timezone.now()
    )
    response = authenticated_client.get(LIST_URL)
    assert response.status_code == 200
    names = [a.account_name for a in response.context["accounts"]]
    assert "Mine" in names
    assert "Theirs" not in names


@pytest.mark.django_db
def test_detail_visible_to_owner(authenticated_client, trading_account):
    response = authenticated_client.get(_detail_url(trading_account.pk))
    assert response.status_code == 200
    assert response.context["account"] == trading_account


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_account(authenticated_client, trading_account):
    response = authenticated_client.post(
        _edit_url(trading_account.pk),
        {
            "account_name": "Renamed Account",
            "broker": "New Broker",
            "last_trade_date": "2025-02-01T12:00",
        },
    )
    assert response.status_code == 302
    trading_account.refresh_from_db()
    assert trading_account.account_name == "Renamed Account"
    assert trading_account.broker == "New Broker"


@pytest.mark.django_db
def test_cannot_edit_others_account(authenticated_client, second_user):
    """A user cannot edit an account that belongs to someone else."""
    theirs = TradingAccount.objects.create(
        user=second_user,
        account_name="Theirs",
        last_trade_date=timezone.now() - timedelta(days=1),
    )
    response = authenticated_client.post(
        _edit_url(theirs.pk),
        {
            "account_name": "Hacked",
            "broker": "x",
            "last_trade_date": "2025-01-01T10:00",
        },
    )
    assert response.status_code == 404
    theirs.refresh_from_db()
    assert theirs.account_name == "Theirs"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_account(authenticated_client, trading_account):
    pk = trading_account.pk
    response = authenticated_client.post(_delete_url(pk))
    assert response.status_code == 302
    assert response.url == LIST_URL
    assert not TradingAccount.objects.filter(pk=pk).exists()


@pytest.mark.django_db
def test_cannot_delete_others_account(authenticated_client, second_user):
    theirs = TradingAccount.objects.create(
        user=second_user, account_name="Theirs", last_trade_date=timezone.now()
    )
    response = authenticated_client.post(_delete_url(theirs.pk))
    assert response.status_code == 404
    assert TradingAccount.objects.filter(pk=theirs.pk).exists()


# ---------------------------------------------------------------------------
# Object isolation sanity
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_detail_404_for_others_account(authenticated_client, second_user):
    theirs = TradingAccount.objects.create(
        user=second_user, account_name="Theirs", last_trade_date=timezone.now()
    )
    response = authenticated_client.get(_detail_url(theirs.pk))
    assert response.status_code == 404
