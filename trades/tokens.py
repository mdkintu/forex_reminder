"""Signed one-click "I traded" links for reminder emails.

The token identifies the account *and* its owner and is signed with
SECRET_KEY under a dedicated salt, so it can't be forged, reused for another
purpose, or used after the account changes hands. It expires after
:data:`TRADED_LINK_MAX_AGE` seconds. The link only works via POST from the
confirmation page it opens (GET never changes anything, because mail scanners
pre-fetch links).
"""

from django.conf import settings
from django.core import signing
from django.urls import reverse

from .models import TradingAccount

TRADED_LINK_SALT = "fair.trades.traded-link"
TRADED_LINK_MAX_AGE = 7 * 24 * 60 * 60  # 7 days


def make_traded_token(account) -> str:
    return signing.dumps({"a": account.pk, "u": account.user_id}, salt=TRADED_LINK_SALT)


def read_traded_token(token: str):
    """The account a valid, unexpired token refers to, or None."""
    try:
        data = signing.loads(token, salt=TRADED_LINK_SALT, max_age=TRADED_LINK_MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        return None
    if not isinstance(data, dict):
        return None
    return (
        TradingAccount.objects.select_related("user")
        .filter(pk=data.get("a"), user_id=data.get("u"))
        .first()
    )


def traded_url(account) -> str:
    """Absolute URL of the account's "I traded" confirmation page."""
    path = reverse("trades:traded_link", args=[make_traded_token(account)])
    return f"{settings.SITE_SCHEME}://{settings.SITE_DOMAIN}{path}"
