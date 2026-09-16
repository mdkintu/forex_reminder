"""Tests for the Telegram webhook that powers the "Connect Telegram" flow."""

import json
from unittest import mock

import pytest
from django.urls import reverse


WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def webhook_secret(settings):
    settings.TELEGRAM_WEBHOOK_SECRET = WEBHOOK_SECRET
    return WEBHOOK_SECRET


@pytest.fixture
def mock_send_telegram():
    with mock.patch("accounts.views.send_telegram_message") as sender:
        yield sender


def _post_update(client, body, secret=WEBHOOK_SECRET):
    headers = {}
    if secret is not None:
        headers["HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN"] = secret
    return client.post(
        reverse("accounts:telegram_webhook"),
        data=json.dumps(body),
        content_type="application/json",
        **headers,
    )


def _start_update(chat_id, token):
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "date": 0,
            "text": f"/start {token}",
        },
    }


@pytest.mark.django_db
def test_webhook_rejects_missing_secret(client):
    response = _post_update(client, _start_update(123, "x"), secret=None)
    assert response.status_code == 403


@pytest.mark.django_db
def test_webhook_rejects_wrong_secret(client):
    response = _post_update(client, _start_update(123, "x"), secret="wrong")
    assert response.status_code == 403


def test_webhook_rejects_get(client, settings):
    settings.TELEGRAM_WEBHOOK_SECRET = WEBHOOK_SECRET
    response = client.get(reverse("accounts:telegram_webhook"))
    assert response.status_code == 405


@pytest.mark.django_db
def test_webhook_connects_valid_token(client, user, mock_send_telegram):
    token = user.get_or_create_telegram_link_token()
    response = _post_update(client, _start_update(555444333, token))

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.telegram_chat_id == "555444333"
    # Token is single-use.
    assert user.telegram_link_token == ""
    mock_send_telegram.assert_called_once()
    assert mock_send_telegram.call_args.args[0] == 555444333


@pytest.mark.django_db
def test_webhook_rejects_expired_or_unknown_token(client, mock_send_telegram):
    response = _post_update(client, _start_update(555444333, "not-a-real-token"))

    assert response.status_code == 200
    mock_send_telegram.assert_called_once()
    # No user should have been connected to this chat.
    from accounts.models import User

    assert not User.objects.filter(telegram_chat_id="555444333").exists()


@pytest.mark.django_db
def test_webhook_ignores_non_start_messages(client, user, mock_send_telegram):
    body = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 42, "type": "private"},
            "date": 0,
            "text": "hello there",
        },
    }
    response = _post_update(client, body)

    assert response.status_code == 200
    mock_send_telegram.assert_not_called()


@pytest.mark.django_db
def test_webhook_ignores_malformed_body(client):
    response = client.post(
        reverse("accounts:telegram_webhook"),
        data="not json",
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=WEBHOOK_SECRET,
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_webhook_does_not_connect_someone_elses_expired_token_to_a_new_chat(
    client, user, second_user, mock_send_telegram
):
    """A token, once used, can't be replayed to hijack the connection later."""
    token = user.get_or_create_telegram_link_token()
    _post_update(client, _start_update(111, token))  # first use: connects fine

    # Replaying the same token (e.g. an old message re-sent) must not connect
    # a second chat to the user.
    response = _post_update(client, _start_update(222, token))
    assert response.status_code == 200

    user.refresh_from_db()
    assert user.telegram_chat_id == "111"  # unchanged by the replay
