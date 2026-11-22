"""Phase 2: Telegram bot commands (/status, /traded, /help) and button callbacks."""

import json
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
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
         mock.patch("accounts.telegram_bot.edit_message_text") as edit, \
         mock.patch("accounts.telegram_bot.edit_message_buttons") as buttons:
        yield {"send": send, "answer": answer, "edit": edit, "buttons": buttons}


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


def _datas(buttons):
    return [data for row in buttons for _, data in row]


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
def test_traded_single_account_asks_now_or_pick(client, user, bot):
    acct = _acct(user, "Only", 20)
    _post(client, _msg("/traded"))
    acct.refresh_from_db()
    assert acct.days_since_last_trade == 20  # nothing recorded until a tap
    assert "Only" in bot["send"].call_args.args[1]
    assert _datas(bot["send"].call_args.kwargs["buttons"]) == [f"traded:{acct.pk}", f"pick:{acct.pk}"]


@pytest.mark.django_db
def test_traded_many_accounts_offers_buttons(client, user, bot):
    a = _acct(user, "Alpha", 20)
    b = _acct(user, "Beta", 15)
    _post(client, _msg("/traded"))
    buttons = bot["send"].call_args.kwargs["buttons"]
    datas = _datas(buttons)
    assert f"traded:{a.pk}" in datas and f"traded:{b.pk}" in datas
    assert f"pick:{a.pk}" in datas and f"pick:{b.pk}" in datas
    a.refresh_from_db()
    assert a.days_since_last_trade == 20  # nothing marked yet


@pytest.mark.django_db
def test_traded_with_argument_matches_name_or_number(client, user, bot):
    a = _acct(user, "Alpha Funded", 20, number="111")
    b = _acct(user, "Beta", 15, number="222")
    _post(client, _msg("/traded 222"))
    assert _datas(bot["send"].call_args.kwargs["buttons"]) == [f"traded:{b.pk}", f"pick:{b.pk}"]
    _post(client, _msg("/traded alpha"))
    assert _datas(bot["send"].call_args.kwargs["buttons"]) == [f"traded:{a.pk}", f"pick:{a.pk}"]
    # "✅ Just now" then records it.
    _post(client, _callback(f"traded:{a.pk}"))
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


# --- date & time picker ------------------------------------------------------

# Sunday 22 Nov 2026, 14:37:20 in Nairobi (UTC+3).
NOW = datetime(2026, 11, 22, 11, 37, 20, tzinfo=dt_timezone.utc)


@pytest.fixture
def nairobi_now(user):
    user.timezone = "Africa/Nairobi"
    user.save(update_fields=["timezone"])
    with mock.patch("django.utils.timezone.now", return_value=NOW):
        yield NOW


def _edited_buttons(bot):
    chat, message_id, buttons = bot["buttons"].call_args.args
    assert (chat, message_id) == (CHAT, 99)
    return buttons


@pytest.mark.django_db
def test_pick_day_step(client, user, bot, nairobi_now):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"pick:{acct.pk}"))
    buttons = _edited_buttons(bot)
    labels = [label for row in buttons for label, _ in row]
    datas = _datas(buttons)
    assert "Alpha" in labels[0] and "Africa/Nairobi" in labels[0] and datas[0] == "noop"
    assert labels[1:3] == ["Today", "Yesterday"] and labels[3] == "Fri 20"
    assert datas[1:8] == [f"pick:{acct.pk}:202611{d}" for d in (22, 21, 20, 19, 18, 17, 16)]
    assert datas[-1] == f"menu:{acct.pk}"
    bot["edit"].assert_not_called()  # the message text is left alone
    bot["answer"].assert_called_once_with("cbq-1")


@pytest.mark.django_db
def test_pick_hour_step_hides_future_hours(client, user, bot, nairobi_now):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"pick:{acct.pk}:20261122"))
    datas = _datas(_edited_buttons(bot))
    hours = [d for d in datas if d.startswith(f"pick:{acct.pk}:20261122:")]
    assert hours == [f"pick:{acct.pk}:20261122:{h:02d}" for h in range(15)]  # 00..14
    assert datas[-1] == f"pick:{acct.pk}"  # « Back to the days

    _post(client, _callback(f"pick:{acct.pk}:20261121"))
    datas = _datas(_edited_buttons(bot))
    assert len([d for d in datas if d.startswith(f"pick:{acct.pk}:20261121:")]) == 24


@pytest.mark.django_db
def test_pick_minute_step_hides_future_minutes(client, user, bot, nairobi_now):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"pick:{acct.pk}:20261122:14"))
    datas = _datas(_edited_buttons(bot))
    assert [d for d in datas if d.startswith("at:")] == [
        f"at:{acct.pk}:20261122:14{m:02d}" for m in range(0, 36, 5)  # :00..:35
    ]
    assert datas[-1] == f"pick:{acct.pk}:20261122"

    _post(client, _callback(f"pick:{acct.pk}:20261121:23"))
    assert len([d for d in _datas(_edited_buttons(bot)) if d.startswith("at:")]) == 12


@pytest.mark.django_db
@pytest.mark.parametrize("args", ["20261123", "20261122:15", "20261122:24", "2026112", "20261340", "20261121:14:00"])
def test_pick_rejects_future_or_bad_steps(client, user, bot, nairobi_now, args):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"pick:{acct.pk}:{args}"))
    bot["buttons"].assert_not_called()
    assert "isn't available" in bot["answer"].call_args.args[1]


@pytest.mark.django_db
def test_at_records_the_local_time(client, user, bot, nairobi_now):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"at:{acct.pk}:20261121:1530"))
    acct.refresh_from_db()
    assert acct.last_trade_date == datetime(2026, 11, 21, 12, 30, tzinfo=dt_timezone.utc)
    chat, message_id, text = bot["edit"].call_args.args
    assert (chat, message_id) == (CHAT, 99)
    assert text.startswith("⚠️ reminder text\n\n✅ 'Alpha' reset")  # reminder text kept
    assert "Nov 21, 15:30" in text
    assert bot["answer"].call_args.args == ("cbq-1", "Trade recorded ✅")


@pytest.mark.django_db
@pytest.mark.parametrize("args", ["20261122:1440", "20261123:0900", "20261121", "20261121:2460", "20261121:930", "x:1530"])
def test_at_rejects_future_or_bad_times(client, user, bot, nairobi_now, args):
    acct = _acct(user, "Alpha", 20)
    before = acct.last_trade_date
    _post(client, _callback(f"at:{acct.pk}:{args}"))
    acct.refresh_from_db()
    assert acct.last_trade_date == before
    bot["edit"].assert_not_called()
    assert "isn't available" in bot["answer"].call_args.args[1]


@pytest.mark.django_db
def test_at_past_the_limit_says_so(client, user, bot, nairobi_now):
    acct = _acct(user, "Alpha", 0)
    acct.inactivity_days = 3
    acct.save(update_fields=["inactivity_days"])
    _post(client, _callback(f"at:{acct.pk}:20261117:0900"))
    acct.refresh_from_db()
    assert acct.is_inactive
    assert "past its 3-day limit" in bot["edit"].call_args.args[2]


@pytest.mark.django_db
@pytest.mark.parametrize("data", ["pick:{pk}", "pick:{pk}:20261121", "at:{pk}:20261121:1530", "menu:{pk}"])
def test_picker_from_other_chat_is_ignored(client, user, second_user, bot, nairobi_now, data):
    acct = _acct(user, "Alpha", 20)
    before = acct.last_trade_date
    second_user.telegram_chat_id = "5555"
    second_user.save()
    _post(client, _callback(data.format(pk=acct.pk), chat=5555))
    acct.refresh_from_db()
    assert acct.last_trade_date == before
    bot["buttons"].assert_not_called()
    bot["edit"].assert_not_called()
    assert bot["answer"].call_args.args[1] == "This button isn't valid for this chat."


@pytest.mark.django_db
def test_noop_only_answers(client, user, bot):
    _post(client, _callback("noop"))
    bot["answer"].assert_called_once_with("cbq-1")
    bot["buttons"].assert_not_called()
    bot["edit"].assert_not_called()


@pytest.mark.django_db
def test_menu_restores_now_or_pick(client, user, bot):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"menu:{acct.pk}"))
    assert _datas(_edited_buttons(bot)) == [f"traded:{acct.pk}", f"pick:{acct.pk}"]


@pytest.mark.django_db
def test_snooze_with_unsupported_days_is_rejected(client, user, bot):
    acct = _acct(user, "Alpha", 20)
    _post(client, _callback(f"snooze:{acct.pk}:2"))
    acct.refresh_from_db()
    assert acct.snoozed_until is None
    assert bot["answer"].call_args.args[1] == "This button isn't valid for this chat."


def test_edit_message_buttons_ignores_not_modified():
    """A double tap re-sends the same buttons; Telegram's 'not modified' error is harmless."""
    import telegram

    from trades import notifications

    fake = mock.Mock()
    fake.edit_message_reply_markup = mock.AsyncMock(
        side_effect=telegram.error.BadRequest("Message is not modified: specified new message content ...")
    )
    with mock.patch.object(notifications, "_bot", return_value=fake):
        assert notifications.edit_message_buttons(CHAT, 99, [[("x", "noop")]]) is None
        fake.edit_message_reply_markup.side_effect = telegram.error.BadRequest("Message to edit not found")
        with pytest.raises(telegram.error.BadRequest):
            notifications.edit_message_buttons(CHAT, 99, [[("x", "noop")]])
    kwargs = fake.edit_message_reply_markup.call_args.kwargs
    assert (kwargs["chat_id"], kwargs["message_id"]) == (CHAT, 99)


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
