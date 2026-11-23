"""Telegram bot logic: handles the updates Telegram posts to our webhook.

Supported:

* ``/start <token>`` — the one-tap "Connect Telegram" flow (links this chat to
  the FAIR user the token belongs to).
* ``/status`` — each account's days left and next reminder, most urgent first.
* ``/traded [name or account #]`` — record a trade. With one account (or an
  unambiguous match) the bot asks "Just now" or "Pick date & time";
  otherwise it replies with those two choices for every account.
* ``/help``.
* Inline-button taps (``callback_query``), all checked against the chat that
  owns the account:

  - ``traded:<pk>`` — record a trade now (on every Telegram reminder too).
  - ``snooze:<pk>:<days>`` — the reminder's "Snooze 1 day" button.
  - ``pick:<pk>[:<YYYYMMDD>[:<HH>]]`` — the date & time picker, one step per
    tap (day → hour → minutes), in the user's own timezone. It swaps the
    message's buttons and leaves its text alone.
  - ``at:<pk>:<YYYYMMDD>:<HHMM>`` — record the trade at that local time.
  - ``menu:<pk>`` — back from the picker to "Just now / Pick date & time".
  - ``noop`` — the picker's header labels; only stops the spinner.

  The picker keeps no state: everything it needs is in the button's data.

Only chats linked to a FAIR user can see or change that user's accounts.
Plain (non-command) messages are ignored. :func:`handle_update` is called by
``accounts.views.telegram_webhook``, which turns any exception into a 200.
"""

import logging
from datetime import datetime, timedelta

from django.utils import timezone

from trades.models import SNOOZE_DAYS, TradingAccount
from trades.notifications import (
    answer_callback_query,
    edit_message_buttons,
    edit_message_text,
    send_telegram_message,
)

from .models import User

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "FAIR — Forex Account Inactivity Reminder\n\n"
    "/status — days left on each account\n"
    "/traded — record a trade, just now or at a date & time you pick "
    "(resets the countdown)\n"
    "/traded <name or account #> — for a specific account\n"
    "/help — this message\n\n"
    "Reminders also have \"✅ I traded\" and \"🕒 Traded earlier…\" buttons."
)

NOT_LINKED_TEXT = (
    "This chat isn't connected to a FAIR account yet. Open your FAIR profile "
    "page and tap “Connect Telegram” to connect it."
)

INVALID_BUTTON_TEXT = "This button isn't valid for this chat."
INVALID_TIME_TEXT = "That date/time isn't available (it may be in the future). Pick again."

#: Bot command menu registered by ``set_telegram_webhook``.
COMMANDS = [
    ("status", "Days left on each account"),
    ("traded", "Record a trade now (resets the countdown)"),
    ("help", "How to use this bot"),
]

#: Callback actions that act on one of the user's accounts (``<action>:<pk>…``).
ACCOUNT_ACTIONS = ("traded", "snooze", "pick", "at", "menu")
#: Callback data of the picker's header labels.
NOOP = "noop"
#: How many days back the picker offers (today included).
PICK_DAYS = 7
#: Minute buttons are offered in steps of this many minutes.
MINUTE_STEP = 5


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


def _mt5_suffix(account):
    if not account.mt5_last_seen:
        return ""
    return " · MT5 quiet" if account.mt5_sync_quiet else " · MT5 ✓"


def _status_line(account):
    if account.is_inactive:
        return f"• {account.account_name}: ⛔ past its {account.inactivity_days}-day limit{_mt5_suffix(account)}"
    days = account.days_remaining
    plural = "day" if days == 1 else "days"
    return (
        f"• {account.account_name}: {days} {plural} left "
        f"(day {account.days_since_last_trade}) — next reminder: "
        f"{account.next_reminder_label}{_mt5_suffix(account)}"
    )


def _status_text(user):
    accounts = sorted(_accounts(user), key=lambda a: a.days_remaining)
    if not accounts:
        return "You have no trading accounts in FAIR yet."
    return "Your accounts (most urgent first):\n\n" + "\n".join(_status_line(a) for a in accounts)


# --- /traded and the "I traded" button -------------------------------------


def _traded_confirmation(account):
    local = timezone.localtime(account.last_trade_date, account.user.get_timezone())
    if account.is_inactive:
        return (
            f"⚠️ '{account.account_name}': last trade recorded at {local:%b %d, %H:%M}, "
            f"which is already past its {account.inactivity_days}-day limit."
        )
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


def _now_buttons(account):
    """The "when did you trade?" choice for one account."""
    return [[("✅ Just now", f"traded:{account.pk}"), ("🕒 Pick date & time", f"pick:{account.pk}")]]


def _handle_traded(chat_id, user, arg):
    accounts = _accounts(user)
    if not accounts:
        send_telegram_message(chat_id, "You have no trading accounts in FAIR yet.")
        return

    candidates = _match(accounts, arg) if arg else accounts
    if len(candidates) == 1:
        account = candidates[0]
        send_telegram_message(
            chat_id,
            f"When did you trade on '{account.account_name}'?",
            buttons=_now_buttons(account),
        )
        return

    if not candidates:  # nothing matched: offer them all
        candidates = accounts
    send_telegram_message(
        chat_id,
        "Which account did you trade on? ✅ = just now, 🕒 = pick the date & time.",
        buttons=[
            [(f"✅ {a.account_name}", f"traded:{a.pk}"), ("🕒 Pick time", f"pick:{a.pk}")]
            for a in candidates
        ],
    )


# --- the date & time picker ---------------------------------------------------


def _local_now(account):
    return timezone.localtime(timezone.now(), account.user.get_timezone())


def _parse_day(value):
    """``"YYYYMMDD"`` -> ``date``, or None."""
    if len(value) != 8 or not value.isdigit():
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _at(day, hour, minute, tz):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _rows(buttons, size):
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]


def _day_label(day, today):
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day:%a %d}"


def _day_buttons(account, now):
    today = now.date()
    days = [today - timedelta(days=n) for n in range(PICK_DAYS)]
    choices = [(_day_label(d, today), f"pick:{account.pk}:{d:%Y%m%d}") for d in days]
    return (
        [[(f"📅 Day you traded on '{account.account_name}' ({now.tzinfo})", NOOP)]]
        + [choices[:2]]
        + _rows(choices[2:], 3)
        + [[("« Back", f"menu:{account.pk}")]]
    )


def _hour_buttons(account, day, now):
    last = now.hour if day == now.date() else 23
    hours = [(f"{h:02d}", f"pick:{account.pk}:{day:%Y%m%d}:{h:02d}") for h in range(last + 1)]
    return (
        [[(f"🗓 {day:%a %d %b} — pick the hour", NOOP)]]
        + _rows(hours, 6)
        + [[("« Back", f"pick:{account.pk}")]]
    )


def _minute_buttons(account, day, hour, now):
    last = now.minute if (day, hour) == (now.date(), now.hour) else 59
    minutes = [
        (f":{m:02d}", f"at:{account.pk}:{day:%Y%m%d}:{hour:02d}{m:02d}")
        for m in range(0, last + 1, MINUTE_STEP)
    ]
    return (
        [[(f"🗓 {day:%a %d %b}, {hour:02d}:__ — pick the minutes", NOOP)]]
        + _rows(minutes, 6)
        + [[("« Back", f"pick:{account.pk}:{day:%Y%m%d}")]]
    )


def _pick_buttons(account, args, now):
    """Buttons for the picker step named by ``args``; None if invalid or in the future."""
    if not args:
        return _day_buttons(account, now)
    day = _parse_day(args[0])
    if day is None or day > now.date() or len(args) > 2:
        return None
    if len(args) == 1:
        return _hour_buttons(account, day, now)
    hour = int(args[1]) if args[1].isdigit() else 99
    if hour > 23 or _at(day, hour, 0, now.tzinfo) > now:
        return None
    return _minute_buttons(account, day, hour, now)


def _parse_when(args, tz):
    """``["YYYYMMDD", "HHMM"]`` -> aware datetime in ``tz``, or None."""
    if len(args) != 2:
        return None
    day, hhmm = _parse_day(args[0]), args[1]
    if day is None or len(hhmm) != 4 or not hhmm.isdigit():
        return None
    hour, minute = int(hhmm[:2]), int(hhmm[2:])
    if hour > 23 or minute > 59:
        return None
    return _at(day, hour, minute, tz)


# --- inline-button taps -------------------------------------------------------


def _append_confirmation(chat_id, message, confirmation):
    """Add ``confirmation`` under the tapped message's text (drops its buttons)."""
    original = message.get("text") or ""
    edit_message_text(
        chat_id,
        message.get("message_id"),
        f"{original}\n\n{confirmation}" if original else confirmation,
    )


def _handle_callback(query):
    query_id = query.get("id")
    data = query.get("data") or ""
    message = query.get("message") or {}
    chat_id = message.get("chat", {}).get("id") or query.get("from", {}).get("id")

    if data == NOOP:  # a picker header label: nothing to do
        answer_callback_query(query_id)
        return

    action, *params = data.split(":")
    pk, args = (params[0], params[1:]) if params else ("", [])
    account = None
    if action in ACCOUNT_ACTIONS and pk.isdigit() and chat_id:
        # Only the owner's linked chat may act on the account.
        account = (
            TradingAccount.objects.select_related("user")
            .filter(pk=int(pk), user__telegram_chat_id=str(chat_id))
            .first()
        )
    if account is None:
        answer_callback_query(query_id, INVALID_BUTTON_TEXT)
        return

    if action == "traded":
        account.mark_traded()
        answer_callback_query(query_id, "Countdown reset ✅")
        _append_confirmation(chat_id, message, _traded_confirmation(account))
    elif action == "snooze":
        _handle_snooze(query_id, chat_id, message, account, args)
    elif action == "menu":
        answer_callback_query(query_id)
        edit_message_buttons(chat_id, message.get("message_id"), _now_buttons(account))
    elif action == "pick":
        buttons = _pick_buttons(account, args, _local_now(account))
        if buttons is None:
            answer_callback_query(query_id, INVALID_TIME_TEXT)
            return
        answer_callback_query(query_id)
        edit_message_buttons(chat_id, message.get("message_id"), buttons)
    else:  # "at"
        when = _parse_when(args, account.user.get_timezone())
        if when is None or when > timezone.now():
            answer_callback_query(query_id, INVALID_TIME_TEXT)
            return
        account.mark_traded(when)
        answer_callback_query(query_id, "Trade recorded ✅")
        _append_confirmation(chat_id, message, _traded_confirmation(account))


def _handle_snooze(query_id, chat_id, message, account, args):
    days = int(args[0]) if args and args[0].isdigit() else None
    if days not in SNOOZE_DAYS:
        answer_callback_query(query_id, INVALID_BUTTON_TEXT)
        return
    account.snooze(days)
    answer_callback_query(query_id, f"Snoozed for {days} day(s) 💤")
    local = timezone.localtime(account.snoozed_until, account.user.get_timezone())
    _append_confirmation(
        chat_id,
        message,
        f"💤 Snoozed until {local:%b %d, %H:%M}. The final reminder before "
        "the deadline still comes through.",
    )
