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


def send_telegram_message(chat_id: str | int, text: str) -> object | None:
    """Send a Telegram message to ``chat_id`` via the configured bot.

    Args:
        chat_id: The recipient's Telegram chat id (str or int).
        text:    Message text.

    Returns:
        The telegram ``Message`` object on success, or ``None`` if not
        configured / skipped.
    """
    bot_token = settings.TELEGRAM_BOT_TOKEN

    if not (bot_token and chat_id):
        logger.warning(
            "[notifications][telegram] Telegram not configured "
            "(TELEGRAM_BOT_TOKEN) or chat_id '%s' missing. Skipping message.",
            chat_id or "unknown",
        )
        return None

    import telegram  # python-telegram-bot, lazy import

    bot = telegram.Bot(token=bot_token)

    # send_message is async in python-telegram-bot v20+; run it via asyncio.
    async def _send():
        return await bot.send_message(chat_id=chat_id, text=text)

    try:
        async def _main():
            return await _send()

        result = asyncio.run(_main())
        logger.info(
            "[notifications][telegram] Sent to chat %s (msg id %s).",
            chat_id,
            getattr(result, "message_id", "?"),
        )
        return result
    except RuntimeError:
        # A loop may already be running in this thread/context; fall back to
        # reusing it.
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(_send())
        logger.info(
            "[notifications][telegram] Sent to chat %s (msg id %s).",
            chat_id,
            getattr(result, "message_id", "?"),
        )
        return result
