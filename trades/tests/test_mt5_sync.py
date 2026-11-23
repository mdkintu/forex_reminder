"""MT5 auto-sync: the endpoint the FAIR Sync EA posts to (trades/api.py)."""

import json
from datetime import timedelta
from datetime import timezone as dt_timezone

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from trades import api
from trades.models import TradingAccount

LOGIN = "80812345"


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()  # rate-limit buckets
    yield
    cache.clear()


@pytest.fixture
def key(user):
    return user.get_or_create_mt5_sync_key()


def _acct(user, days_ago=10, number=LOGIN, name="FN 100k", **extra):
    return TradingAccount.objects.create(
        user=user, account_name=name, account_number=number,
        last_trade_date=timezone.now() - timedelta(days=days_ago), **extra,
    )


def _post(client, body, key=None, header="Authorization"):
    headers = {}
    if key is not None:
        headers = {"HTTP_AUTHORIZATION": f"Bearer {key}"} if header == "Authorization" else {"HTTP_X_FAIR_KEY": key}
    data = body if isinstance(body, str) else json.dumps(body)
    return client.post(reverse("mt5_sync"), data=data, content_type="application/json", **headers)


def _ts(dt):
    return int(dt.timestamp())


# --- auth and validation -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("bad_key", [None, "", "wrong-key"])
def test_missing_or_wrong_key_is_401(client, user, key, bad_key):
    acct = _acct(user)
    response = _post(client, {"login": LOGIN, "last_open_utc": _ts(timezone.now())}, key=bad_key)
    assert response.status_code == 401
    acct.refresh_from_db()
    assert acct.days_since_last_trade == 10 and acct.mt5_last_seen is None


@pytest.mark.django_db
def test_x_fair_key_header_works_too(client, user, key):
    _acct(user)
    assert _post(client, {"login": LOGIN, "last_open_utc": None}, key=key, header="X-FAIR-Key").status_code == 200


@pytest.mark.django_db
def test_inactive_user_key_is_rejected(client, user, key):
    _acct(user)
    user.is_active = False
    user.save()
    assert _post(client, {"login": LOGIN}, key=key).status_code == 401


@pytest.mark.django_db
def test_get_not_allowed(client, user, key):
    assert client.get(reverse("mt5_sync"), HTTP_AUTHORIZATION=f"Bearer {key}").status_code == 405


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[1, 2]",
        {"last_open_utc": 1764000000},                 # no login
        {"login": "", "last_open_utc": 1764000000},
        {"login": True},
        {"login": LOGIN, "last_open_utc": "yesterday"},
        {"login": LOGIN, "last_open_utc": True},
        {"login": LOGIN, "last_open_utc": 10**20},      # out of range
    ],
)
def test_bad_body_is_400(client, user, key, body):
    acct = _acct(user)
    response = _post(client, body, key=key)
    assert response.status_code == 400
    assert response.json()["ok"] is False
    acct.refresh_from_db()
    assert acct.mt5_last_seen is None


@pytest.mark.django_db
def test_unknown_login_is_404_and_other_users_accounts_never_match(client, user, second_user, key):
    theirs = _acct(second_user)  # same number, different owner
    response = _post(client, {"login": LOGIN, "last_open_utc": _ts(timezone.now())}, key=key)
    assert response.status_code == 404
    assert LOGIN in response.json()["error"]
    theirs.refresh_from_db()
    assert theirs.days_since_last_trade == 10 and theirs.mt5_last_seen is None


# --- syncing -------------------------------------------------------------------


@pytest.mark.django_db
def test_newer_open_time_resets_countdown_and_clears_snooze(client, user, key):
    acct = _acct(user, snoozed_until=timezone.now() + timedelta(days=2))
    opened = (timezone.now() - timedelta(hours=2)).replace(microsecond=0)
    response = _post(client, {"login": int(LOGIN), "server": "FundedNext-Server 2",
                              "last_open_utc": _ts(opened), "deal": 991, "ea": "1.0"}, key=key)
    assert response.status_code == 200
    acct.refresh_from_db()
    assert acct.last_trade_date == opened
    assert acct.snoozed_until is None
    assert acct.mt5_last_seen is not None
    (result,) = response.json()["accounts"]
    assert result["updated"] is True and result["name"] == "FN 100k"
    assert result["last_trade_utc"] == opened.astimezone(dt_timezone.utc).isoformat()


@pytest.mark.django_db
def test_older_open_time_is_ignored(client, user, key):
    acct = _acct(user, days_ago=1)
    before = acct.last_trade_date
    response = _post(client, {"login": LOGIN, "last_open_utc": _ts(before - timedelta(days=5))}, key=key)
    assert response.status_code == 200 and response.json()["accounts"][0]["updated"] is False
    acct.refresh_from_db()
    assert acct.last_trade_date == before
    assert acct.mt5_last_seen is not None  # still counts as a check-in


@pytest.mark.django_db
def test_future_open_time_is_capped_at_now(client, user, key):
    acct = _acct(user)
    _post(client, {"login": LOGIN, "last_open_utc": _ts(timezone.now() + timedelta(hours=3))}, key=key)
    acct.refresh_from_db()
    assert acct.last_trade_date <= timezone.now()
    assert acct.days_since_last_trade == 0


@pytest.mark.django_db
def test_heartbeat_without_trade_only_updates_last_seen(client, user, key):
    acct = _acct(user)
    before = acct.last_trade_date
    response = _post(client, {"login": LOGIN, "last_open_utc": None}, key=key)
    assert response.status_code == 200
    acct.refresh_from_db()
    assert acct.last_trade_date == before
    assert timezone.now() - acct.mt5_last_seen < timedelta(minutes=1)


@pytest.mark.django_db
def test_repeated_report_is_harmless(client, user, key):
    acct = _acct(user)
    body = {"login": LOGIN, "last_open_utc": _ts(timezone.now() - timedelta(hours=1))}
    assert _post(client, body, key=key).json()["accounts"][0]["updated"] is True
    assert _post(client, body, key=key).json()["accounts"][0]["updated"] is False
    acct.refresh_from_db()
    assert acct.days_since_last_trade in (0, 1)


@pytest.mark.django_db
def test_all_accounts_with_that_number_are_updated(client, user, key):
    a = _acct(user, name="Phase 1")
    b = _acct(user, name="Phase 1 copy")
    other = _acct(user, number="999", name="Other")
    response = _post(client, {"login": LOGIN, "last_open_utc": _ts(timezone.now())}, key=key)
    assert {r["name"] for r in response.json()["accounts"]} == {"Phase 1", "Phase 1 copy"}
    for acct in (a, b, other):
        acct.refresh_from_db()
    assert a.days_since_last_trade == b.days_since_last_trade == 0
    assert other.days_since_last_trade == 10 and other.mt5_last_seen is None


@pytest.mark.django_db
def test_rate_limit(client, user, key, monkeypatch):
    _acct(user)
    monkeypatch.setattr(api, "RATE_LIMIT_PER_MINUTE", 2)
    codes = [_post(client, {"login": LOGIN}, key=key).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# --- quiet-sync display --------------------------------------------------------


@pytest.mark.django_db
def test_mt5_sync_quiet(user):
    acct = _acct(user)
    assert acct.mt5_sync_quiet is False  # never synced: not "quiet"
    acct.mt5_last_seen = timezone.now() - timedelta(hours=2)
    assert acct.mt5_sync_quiet is False
    acct.mt5_last_seen = timezone.now() - timedelta(hours=25)
    assert acct.mt5_sync_quiet is True


@pytest.mark.django_db
def test_daily_report_lists_quiet_mt5_accounts(user):
    from trades.reporting import build_daily_report

    _acct(user, name="Fresh", mt5_last_seen=timezone.now() - timedelta(hours=1))
    _acct(user, name="Gone quiet", number="111", mt5_last_seen=timezone.now() - timedelta(days=2))
    _acct(user, name="Never synced", number="222")
    report = build_daily_report()
    assert "MT5 sync quiet" in report
    assert "Gone quiet" in report
    assert "Fresh" not in report and "Never synced" not in report


@pytest.mark.django_db
def test_daily_report_has_no_mt5_section_when_all_fine(user):
    from trades.reporting import build_daily_report

    _acct(user, mt5_last_seen=timezone.now())
    assert "MT5 sync quiet" not in build_daily_report()


@pytest.mark.django_db
def test_dashboard_and_detail_show_sync_state(client, user):
    client.force_login(user)
    fresh = _acct(user, name="Fresh", mt5_last_seen=timezone.now() - timedelta(minutes=3))
    quiet = _acct(user, name="Quiet", number="111", mt5_last_seen=timezone.now() - timedelta(days=2))
    never = _acct(user, name="Never", number="222")

    dashboard = client.get(reverse("accounts:dashboard")).content.decode()
    assert "MT5 sync · checked in" in dashboard
    assert "MT5 sync quiet since" in dashboard

    assert "Checked in" in client.get(reverse("trades:detail", args=[fresh.pk])).content.decode()
    assert "Quiet since" in client.get(reverse("trades:detail", args=[quiet.pk])).content.decode()
    assert "how to connect MT5" in client.get(reverse("trades:detail", args=[never.pk])).content.decode()
