"""Phase 2: Telegram bot commands (/status, /traded, /help) and button callbacks."""

import json
from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from trades.models import TradingAccount

SECRET = "test-webhook-secret"
CHAT = 987654321  # matches the `user` fixture's telegram_chat_id


@pytest.fixture(autouse=True)
def webhook_secret(settings):
    settings.TELEGRAM_WEBHOOK_SECRET = SECRET


@pytest.fixture
def bot():
    with mock.patch("accounts.telegram_bot.send_telegram_message") as send, \
         mock.patch("accounts.telegram_bot.answer_callback_query") as answer, \
         mock.patch("accounts.telegram_bot.edit_message_text") as edit:
        yield {"send": send, "answer": answer, "edit": edit}


def _post(client, body):
    return client.post(
        reverse("accounts:telegram_webhook"),
        data=json.dumps(body),
        content_type="application/json",
        HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SECRET,
    )


def _msg(text, chat=CHAT):
    return {"update_id": 1, "message": {"message_id": 7, "chat": {"id": chat}, "date": 0, "text": text}}


def _callback(data, chat=CHAT):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cbq-1",
            "from": {"id": chat},
            "data": data,
            "message": {"message_id": 99, "chat": {"id": chat}, "text": "⚠️ reminder text"},
        },
    }


def _acct(user, name, days, number=""):
    return TradingAccount.objects.create(
        user=user, account_name=name, account_number=number,
        last_trade_date=timezone.now() - timedelta(days=days),
    )


@pytest.mark.django_db
def test_status_lists_accounts(client, user, bot):
    _acct(user, "Alpha", 20)
    _acct(user, "Beta", 3)
    assert _post(client, _msg("/status")).status_code == 200
    text = bot["send"].call_args.args[1]
    assert "Alpha" in text and "10 days left" in text
    assert "Beta" in text and "27 days left" in text
    # Most urgent first.
    assert text.index("Alpha") < text.index("Beta")


@pytest.mark.django_db
def test_status_with_bot_username_suffix(client, user, bot):
    _acct(user, "Alpha", 20)
    _post(client, _msg("/status@FairBot"))
    assert "Alpha" in bot["send"].call_args.args[1]


@pytest.mark.django_db
def test_traded_single_account_marks_it(client, user, bot):
    acct = _acct(user, "Only", 20)
    _post(client, _msg("/traded"))
    acct.refresh_from_db()
    assert acct.days_since_last_trade == 0
    assert "Only" in bot["send"].call_args.args[1]


@pytest.mark.django_db
def test_traded_many_accounts_offers_buttons(client, user, bot):
    a = _acct(user, "Alpha", 20)
    b = _acct(user, "Beta", 15)
    _post(client, _msg("/traded"))
    buttons = bot["send"].call_args.kwargs["buttons"]
    datas = [data for row in buttons for _, data in row]
    assert f"traded:{a.pk}" in datas and f"traded:{b.pk}" in datas
    a.refresh_from_db()
    assert a.days_since_last_trade == 20  # nothing marked yet


@pytest.mark.django_db
def test_traded_with_argument_matches_name_or_number(client, user, bot):
    a = _acct(user, "Alpha Funded", 20, number="111")
    b = _acct(user, "Beta", 15, number="222")
    _post(client, _msg("/traded 222"))
    b.refresh_from_db()
    assert b.days_since_last_trade == 0
    _post(client, _msg("/traded alpha"))
    a.refresh_from_db()
    assert a.days_since_last_trade == 0


@pytest.mark.django_db
def test_callback_marks_account_and_edits_message(client, user, bot):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"traded:{acct.pk}"))
    acct.refresh_from_db()
    assert acct.days_since_last_trade == 0
    bot["answer"].assert_called_once()
    assert bot["answer"].call_args.args[0] == "cbq-1"
    chat, message_id, text = bot["edit"].call_args.args
    assert (chat, message_id) == (CHAT, 99) and "✅" in text


@pytest.mark.django_db
def test_callback_from_other_chat_is_ignored(client, user, second_user, bot):
    acct = _acct(user, "Alpha", 20)
    second_user.telegram_chat_id = "5555"
    second_user.save()
    _post(client, _callback(f"traded:{acct.pk}", chat=5555))
    acct.refresh_from_db()
    assert acct.days_since_last_trade == 20
    bot["edit"].assert_not_called()
    bot["answer"].assert_called_once()  # always answer so the spinner stops


@pytest.mark.django_db
def test_unlinked_chat_is_told_to_connect(client, user, bot):
    _post(client, _msg("/status", chat=31337))
    assert "connect" in bot["send"].call_args.args[1].lower()


@pytest.mark.django_db
def test_help(client, user, bot):
    _post(client, _msg("/help"))
    text = bot["send"].call_args.args[1]
    assert "/status" in text and "/traded" in text


@pytest.mark.django_db
def test_plain_text_still_ignored(client, user, bot):
    _post(client, _msg("hello"))
    bot["send"].assert_not_called()


@pytest.mark.django_db
def test_bot_errors_never_500(client, user, bot):
    _acct(user, "Alpha", 20)
    bot["send"].side_effect = RuntimeError("Telegram down")
    assert _post(client, _msg("/status")).status_code == 200


# --- set_telegram_webhook registers callbacks + command menu --------------


def test_set_webhook_registers_callbacks_and_commands(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:abc"
    settings.TELEGRAM_WEBHOOK_SECRET = SECRET
    settings.SITE_SCHEME, settings.SITE_DOMAIN = "https", "fair.example.com"
    with mock.patch("telegram.Bot") as Bot:
        inst = Bot.return_value
        inst.set_webhook = mock.AsyncMock()
        inst.set_my_commands = mock.AsyncMock()
        call_command("set_telegram_webhook", stdout=StringIO())

    kwargs = inst.set_webhook.call_args.kwargs
    assert set(kwargs["allowed_updates"]) == {"message", "callback_query"}
    commands = [c.command for c in inst.set_my_commands.call_args.args[0]]
    assert {"status", "traded", "help"} <= set(commands)
