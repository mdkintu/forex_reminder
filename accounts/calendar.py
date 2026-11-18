"""A private iCalendar (.ics) feed of a user's inactivity deadlines.

Calendar apps (Google, Apple, Outlook) subscribe to the URL and refresh it
periodically, so deadlines move automatically when the user records a trade.
Written by hand (RFC 5545) to avoid a dependency: CRLF line endings, text
escaping, and lines folded at 75 octets.
"""

from datetime import timezone as dt_timezone

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

#: Reminder alarms attached to each deadline event.
ALARMS = ("-P3D", "-P1D")


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> list[str]:
    """Split a content line into <=75-octet pieces (continuations start with a
    space), never breaking inside a UTF-8 character."""
    pieces, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        limit = 75 if not pieces else 74  # continuation lines carry a leading space
        if size + width > limit:
            pieces.append(current)
            current, size = "", 0
        current += char
        size += width
    pieces.append(current)
    return [pieces[0]] + [" " + p for p in pieces[1:]]


def _utc(dt) -> str:
    return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(user) -> str:
    """The user's feed: one event per account still before its deadline."""
    utc = _utc

    base = f"{settings.SITE_SCHEME}://{settings.SITE_DOMAIN}"
    now = utc(timezone.now())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//FAIR//Inactivity deadlines//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:FAIR inactivity deadlines",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for account in user.trading_accounts.order_by("last_trade_date"):
        if account.is_inactive:
            continue
        deadline = account.deadline
        number = f" (#{account.account_number})" if account.account_number else ""
        summary = f"⚠️ Trade deadline: {account.account_name}{number}"
        description = (
            f"'{account.account_name}' reaches its {account.inactivity_days}-day "
            f"inactivity limit at this time unless you place a trade. "
            f"Last trade: {timezone.localtime(account.last_trade_date, user.get_timezone()):%Y-%m-%d %H:%M}."
        )
        lines += [
            "BEGIN:VEVENT",
            f"UID:fair-account-{account.pk}@{settings.SITE_DOMAIN}",
            f"DTSTAMP:{now}",
            f"DTSTART:{utc(deadline)}",
            f"DTEND:{utc(deadline + timezone.timedelta(minutes=30))}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
            f"URL:{base}{reverse('trades:detail', args=[account.pk])}",
        ]
        for trigger in ALARMS:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"TRIGGER:{trigger}",
                f"DESCRIPTION:{_escape(summary)}",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    folded = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"
