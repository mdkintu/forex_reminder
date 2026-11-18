"""Telegram bot logic: handles the updates Telegram posts to our webhook.

Supported:

* ``/start <token>`` — the one-tap "Connect Telegram" flow (links this chat to
  the FAIR user the token belongs to).
* ``/status`` — each account's days left and next reminder, most urgent first.
* ``/traded [name or account #]`` — record a trade now. With one account (or
  an unambiguous match) it's marked immediately; otherwise the bot replies
  with one button per account.
* ``/help``.
* Inline-button taps (``callback_query``) with data ``traded:<account pk>`` —
  sent on every Telegram reminder and by ``/traded``.

Only chats linked to a FAIR user can see or change that user's accounts.
Plain (non-command) messages are ignored. :func:`handle_update` is called by
``accounts.views.telegram_webhook``, which turns any exception into a 200.
"""

import logging

from django.utils import timezone

from trades.models import TradingAccount
from trades.notifications import (
    answer_callback_query,
    edit_message_text,
    send_telegram_message,
)

from .models import User

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "FAIR — Forex Account Inactivity Reminder\n\n"
    "/status — days left on each account\n"
    "/traded — record a trade now (resets the countdown)\n"
    "/traded <name or account #> — for a specific account\n"
    "/help — this message\n\n"
    "Reminders also have an \"✅ I traded\" button."
)

NOT_LINKED_TEXT = (
    "This chat isn't connected to a FAIR account yet. Open your FAIR profile "
    "page and tap “Connect Telegram” to connect it."
)

#: Bot command menu registered by ``set_telegram_webhook``.
COMMANDS = [
    ("status", "Days left on each account"),
    ("traded", "Record a trade now (resets the countdown)"),
    ("help", "How to use this bot"),
]


def handle_update(update: dict) -> None:
    """Dispatch one Telegram update (already parsed from JSON)."""
    if update.get("callback_query"):
        _handle_callback(update["callback_query"])
        return

    message = update.get("message") or update.get("edited_message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text.startswith("/"):
        return  # ignore plain chat messages

    command, _, arg = text.partition(" ")
    command = command.split("@", 1)[0].lower()  # "/status@FairBot" -> "/status"
    arg = arg.strip()

    if command == "/start":
        _handle_start(chat_id, arg)
        return

    user = _linked_user(chat_id)
    if command == "/help":
        send_telegram_message(chat_id, HELP_TEXT if user else NOT_LINKED_TEXT)
    elif command in ("/status", "/traded"):
        if user is None:
            send_telegram_message(chat_id, NOT_LINKED_TEXT)
        elif command == "/status":
            send_telegram_message(chat_id, _status_text(user))
        else:
            _handle_traded(chat_id, user, arg)
    # Unknown commands are ignored.


def _linked_user(chat_id):
    return User.objects.filter(telegram_chat_id=str(chat_id)).first()


def _accounts(user):
    return list(TradingAccount.objects.filter(user=user).select_related("user"))


# --- /start <token> --------------------------------------------------------


def _handle_start(chat_id, token):
    if not token:
        user = _linked_user(chat_id)
        send_telegram_message(chat_id, HELP_TEXT if user else NOT_LINKED_TEXT)
        return

    user = User.resolve_telegram_link_token(token)
    if user is None:
        send_telegram_message(
            chat_id,
            "This link has expired or isn't valid. Go back to your FAIR "
            "profile page and tap “Connect Telegram” again.",
        )
        return

    # Save first: the connection itself must not be lost even if the
    # confirmation reply below fails to send (network blip, Telegram API
    # error, etc.) — a retried webhook delivery would otherwise find the
    # token already cleared and wrongly report it as expired.
    user.telegram_chat_id = str(chat_id)
    user.save(update_fields=["telegram_chat_id"])
    user.clear_telegram_link_token()

    logger.info("[telegram bot] Connected chat %s to user %s.", chat_id, user.email)
    send_telegram_message(
        chat_id,
        "✅ Telegram connected! You'll receive FAIR inactivity reminders here.\n\n"
        + HELP_TEXT,
    )


# --- /status ----------------------------------------------------------------


def _status_line(account):
    if account.is_inactive:
        return f"• {account.account_name}: ⛔ past its {account.inactivity_days}-day limit"
    days = account.days_remaining
    plural = "day" if days == 1 else "days"
    return (
        f"• {account.account_name}: {days} {plural} left "
        f"(day {account.days_since_last_trade}) — next reminder: "
        f"{account.next_reminder_label}"
    )


def _status_text(user):
    accounts = sorted(_accounts(user), key=lambda a: a.days_remaining)
    if not accounts:
        return "You have no trading accounts in FAIR yet."
    return "Your accounts (most urgent first):\n\n" + "\n".join(_status_line(a) for a in accounts)


# --- /traded and the "I traded" button -------------------------------------


def _traded_confirmation(account):
    local = timezone.localtime(account.last_trade_date, account.user.get_timezone())
    return (
        f"✅ '{account.account_name}' reset — last trade recorded at "
        f"{local:%b %d, %H:%M}. Next reminder: {account.next_reminder_label}."
    )


def _match(accounts, arg):
    """Accounts matching ``arg`` by exact account number, else by name."""
    needle = arg.lower()
    by_number = [a for a in accounts if a.account_number and a.account_number.lower() == needle]
    if by_number:
        return by_number
    return [a for a in accounts if needle in a.account_name.lower()]


def _handle_traded(chat_id, user, arg):
    accounts = _accounts(user)
    if not accounts:
        send_telegram_message(chat_id, "You have no trading accounts in FAIR yet.")
        return

    candidates = _match(accounts, arg) if arg else accounts
    if len(candidates) == 1:
        account = candidates[0]
        account.mark_traded()
        send_telegram_message(chat_id, _traded_confirmation(account))
        return

    if not candidates:  # nothing matched: offer them all
        candidates = accounts
    send_telegram_message(
        chat_id,
        "Which account did you trade on?",
        buttons=[[(f"✅ {a.account_name}", f"traded:{a.pk}")] for a in candidates],
    )


def _handle_callback(query):
    query_id = query.get("id")
    data = query.get("data") or ""
    message = query.get("message") or {}
    chat_id = message.get("chat", {}).get("id") or query.get("from", {}).get("id")

    action, _, pk = data.partition(":")
    account = None
    if action == "traded" and pk.isdigit() and chat_id:
        # Only the owner's linked chat may act on the account.
        account = (
            TradingAccount.objects.select_related("user")
            .filter(pk=int(pk), user__telegram_chat_id=str(chat_id))
            .first()
        )

    if account is None:
        answer_callback_query(query_id, "This button isn't valid for this chat.")
        return

    account.mark_traded()
    answer_callback_query(query_id, "Countdown reset ✅")
    confirmation = _traded_confirmation(account)
    original = message.get("text") or ""
    edit_message_text(
        chat_id,
        message.get("message_id"),
        f"{original}\n\n{confirmation}" if original else confirmation,
    )
