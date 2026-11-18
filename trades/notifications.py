"""
Notification sending helpers for WhatsApp (Twilio) and Telegram.

These are thin wrappers around the Twilio and python-telegram-bot SDKs so the
reminder task can send real messages. Credentials are read from environment
variables (see .env.example):

  * WhatsApp/Twilio: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
  * Telegram:        TELEGRAM_BOT_TOKEN

If the required credentials are missing, the functions log a clear warning and
return without sending, so development never crashes.
"""

import asyncio
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

#: Number of attempts when sending a Telegram message (transient network blips
#: to api.telegram.org are not uncommon, so a couple of retries help).
TELEGRAM_MAX_ATTEMPTS = 3

#: Seconds to allow for the Telegram API connection + read/write phases.
TELEGRAM_CONNECT_TIMEOUT = 30.0
TELEGRAM_READ_TIMEOUT = 30.0

def send_whatsapp_message(to: str, body: str) -> str | None:
    """Send a WhatsApp message to ``to`` via Twilio.

    Args:
        to:   Recipient phone number in E.164 format, e.g. "+15551234567".
        body: Message text.

    Returns:
        The Twilio message SID on success, or ``None`` if not configured /
        skipped.
    """
    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_WHATSAPP_FROM

    if not (account_sid and auth_token and from_number and to):
        logger.warning(
            "[notifications][whatsapp] Twilio not fully configured "
            "(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM) "
            "or recipient '%s' missing. Skipping WhatsApp message.",
            to or "unknown",
        )
        return None

    from twilio.rest import Client  # lazy import keeps worker startup light

    client = Client(account_sid, auth_token)
    # Twilio WhatsApp numbers are like 'whatsapp:+15551234567'.
    message = client.messages.create(
        from_="whatsapp:" + from_number,
        to="whatsapp:" + to,
        body=body,
    )
    logger.info(
        "[notifications][whatsapp] Sent to %s (SID %s).", to, message.sid
    )
    return message.sid


def _bot():
    """A python-telegram-bot ``Bot`` with generous timeouts, or None if no token."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return None

    import telegram  # python-telegram-bot, lazy import

    # python-telegram-bot v20+/v22 applies HTTP timeouts via the request
    # object (default connect/read/write are only ~5s, which is too tight for
    # slower networks). Give generous, configurable timeouts here.
    from telegram.request import HTTPXRequest

    request = HTTPXRequest(
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT,
        read_timeout=TELEGRAM_READ_TIMEOUT,
        write_timeout=TELEGRAM_READ_TIMEOUT,
        pool_timeout=TELEGRAM_READ_TIMEOUT,
    )
    return telegram.Bot(token=settings.TELEGRAM_BOT_TOKEN, request=request)


def _run_bot(call):
    """Run ``await call(bot)`` synchronously, retrying on timeouts.

    The bot API is async in python-telegram-bot v20+. From plain sync code
    (cron, views) we use ``asyncio.run``; if an event loop is already running
    in this thread, the call runs on a fresh loop in a worker thread instead.
    Returns None when Telegram isn't configured.
    """
    bot = _bot()
    if bot is None:
        return None

    import telegram

    async def _with_retries():
        for attempt in range(1, TELEGRAM_MAX_ATTEMPTS + 1):
            try:
                return await call(bot)
            except telegram.error.TimedOut:
                if attempt < TELEGRAM_MAX_ATTEMPTS:
                    logger.warning(
                        "[notifications][telegram] Timed out on attempt %s/%s; retrying.",
                        attempt,
                        TELEGRAM_MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(2 * attempt)  # small backoff
                    continue
                raise

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_with_retries())  # normal case: no loop running

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _with_retries()).result()


def _keyboard(buttons):
    """[[(label, callback_data), ...], ...] -> InlineKeyboardMarkup (or None)."""
    if not buttons:
        return None
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=data) for label, data in row] for row in buttons]
    )


def send_telegram_message(chat_id: str | int, text: str, buttons=None) -> object | None:
    """Send a Telegram message to ``chat_id`` via the configured bot.

    Args:
        chat_id: The recipient's Telegram chat id (str or int).
        text:    Message text.
        buttons: Optional inline keyboard as rows of ``(label, callback_data)``
                 tuples, e.g. ``[[("✅ I traded", "traded:5")]]``.

    Returns:
        The telegram ``Message`` object on success, or ``None`` if not
        configured / skipped.
    """
    if not (settings.TELEGRAM_BOT_TOKEN and chat_id):
        logger.warning(
            "[notifications][telegram] Telegram not configured "
            "(TELEGRAM_BOT_TOKEN) or chat_id '%s' missing. Skipping message.",
            chat_id or "unknown",
        )
        return None

    result = _run_bot(
        lambda bot: bot.send_message(chat_id=chat_id, text=text, reply_markup=_keyboard(buttons))
    )
    logger.info(
        "[notifications][telegram] Sent to chat %s (msg id %s).",
        chat_id,
        getattr(result, "message_id", "?"),
    )
    return result


def answer_callback_query(callback_query_id: str, text: str = "") -> object | None:
    """Acknowledge an inline-button tap (stops the button's loading spinner)."""
    return _run_bot(
        lambda bot: bot.answer_callback_query(callback_query_id=callback_query_id, text=text or None)
    )


def edit_message_text(chat_id, message_id, text: str) -> object | None:
    """Replace the text of a message the bot sent earlier (drops its buttons)."""
    return _run_bot(
        lambda bot: bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    )
