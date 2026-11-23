"""MT5 auto-sync: the endpoint the FAIR Sync Expert Advisor (mt5/FAIR_Sync.mq5) calls.

``POST /api/mt5/sync/`` with ``Authorization: Bearer <User.mt5_sync_key>`` (or
``X-FAIR-Key: <key>``) and::

    {"login": 12345678, "server": "FundedNext-Server 2",
     "last_open_utc": 1764000000, "deal": 991, "ea": "1.0"}

``last_open_utc`` is the UTC unix time of the newest deal that *opened* a
position (prop firms reset inactivity when a trade is placed, so closes are
ignored), or null when the EA found none. The EA calls on start, on every new
deal and every 15 minutes as a heartbeat; repeating a report changes nothing.

For each of the key owner's accounts whose account number equals ``login``:

* ``mt5_last_seen`` is set to now (heartbeat, always);
* if ``last_open_utc`` (capped at now) is newer than ``last_trade_date``, the
  countdown restarts from it and any snooze is cleared. It only ever moves
  forward, so an old or replayed report can't undo a newer trade recorded
  another way (website, Telegram, email link).

Responses: 200 with the accounts' state, 400 bad body, 401 bad key, 404 no
account with that number, 429 more than RATE_LIMIT_PER_MINUTE calls a minute.
"""

import json
import logging
from datetime import datetime
from datetime import timezone as dt_timezone

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import User

from .models import TradingAccount

logger = logging.getLogger(__name__)

#: Calls allowed per user per minute (the EA makes ~1 every 15 minutes plus
#: one per trade).
RATE_LIMIT_PER_MINUTE = 60


def _error(status, message):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _sync_key(request):
    """The key from ``Authorization: Bearer …``, else ``X-FAIR-Key`` (the EA
    sends both, because some Apache/cPanel setups drop Authorization)."""
    scheme, _, key = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and key.strip():
        return key.strip()
    return request.headers.get("X-FAIR-Key", "").strip()


def _over_rate_limit(user):
    bucket = f"fair:mt5-sync:{user.pk}:{int(timezone.now().timestamp() // 60)}"
    if cache.add(bucket, 1, 120):
        return False
    try:
        return cache.incr(bucket) > RATE_LIMIT_PER_MINUTE
    except ValueError:  # the bucket expired between add() and incr()
        return False


def _parse(body):
    """``(login, last_open datetime or None)``, or a string describing the error."""
    try:
        payload = json.loads(body or b"{}")
    except (TypeError, ValueError):
        return "Body must be JSON."
    if not isinstance(payload, dict):
        return "Body must be a JSON object."

    login = payload.get("login")
    if isinstance(login, bool) or not isinstance(login, (int, str)):
        return "'login' (the MT5 account number) is required."
    login = str(login).strip()
    if not login or len(login) > 50:
        return "'login' (the MT5 account number) is required."

    ts = payload.get("last_open_utc")
    if ts is None:
        return login, None
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return "'last_open_utc' must be a unix timestamp or null."
    try:
        return login, datetime.fromtimestamp(ts, tz=dt_timezone.utc)
    except (OverflowError, OSError, ValueError):
        return "'last_open_utc' is out of range."


@csrf_exempt
@require_POST
def mt5_sync(request):
    key = _sync_key(request)
    user = User.objects.filter(mt5_sync_key=key, is_active=True).first() if key else None
    if user is None:
        return _error(401, "Unknown sync key. Download the EA again from your FAIR profile.")
    if _over_rate_limit(user):
        return _error(429, "Too many requests; slow down.")

    parsed = _parse(request.body)
    if isinstance(parsed, str):
        return _error(400, parsed)
    login, last_open = parsed

    accounts = list(TradingAccount.objects.filter(user=user, account_number__iexact=login).select_related("user"))
    if not accounts:
        return _error(
            404,
            f"No FAIR account has account number {login}. On FAIR, set the account's "
            "number to this MT5 login.",
        )

    now = timezone.now()
    if last_open and last_open > now:  # PC clock or server-offset drift
        last_open = now

    results = []
    for account in accounts:
        TradingAccount.objects.filter(pk=account.pk).update(mt5_last_seen=now)
        updated = False
        if last_open:
            # Conditional update = forward-only even if a newer trade is being
            # recorded another way at the same moment.
            updated = bool(
                TradingAccount.objects.filter(pk=account.pk, last_trade_date__lt=last_open).update(
                    last_trade_date=last_open, snoozed_until=None, updated_at=now
                )
            )
        if updated:
            logger.info(
                "[mt5 sync] '%s' (#%s, user %s): last trade -> %s (from MT5).",
                account.account_name, login, user.pk, last_open.isoformat(),
            )
            account.last_trade_date, account.snoozed_until = last_open, None
        results.append(
            {
                "name": account.account_name,
                "updated": updated,
                "last_trade_utc": account.last_trade_date.astimezone(dt_timezone.utc).isoformat(),
                "days_left": account.days_remaining,
            }
        )
    return JsonResponse({"ok": True, "accounts": results})
