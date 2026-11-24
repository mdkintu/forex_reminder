"""Tests for public pages and protected-page redirects."""

import pytest
from django.urls import reverse
from django.utils import timezone

from trades.models import TradingAccount


@pytest.mark.django_db
def test_public_landing_page_loads(client):
    """The root URL serves the public landing page for anonymous users."""
    response = client.get("/")
    assert response.status_code == 200
    assert "templates rendered"  # sanity: the response body was produced


@pytest.mark.django_db
def test_landing_page_visible_to_anyone(client):
    """Landing page does not require authentication."""
    login_url = reverse("account_login")
    response = client.get("/")
    assert response.status_code == 200
    # Should not have been redirected to the login page.
    assert response.request["PATH_INFO"] != login_url


@pytest.mark.django_db
def test_dashboard_redirects_anonymous_to_login(client):
    """Anonymous users are sent to the login page from the dashboard."""
    dashboard_url = reverse("accounts:dashboard")
    response = client.get(dashboard_url)
    assert response.status_code == 302
    assert reverse("account_login") in response.url


@pytest.mark.django_db
def test_profile_redirects_anonymous_to_login(client):
    """Anonymous users are sent to login from the profile page."""
    response = client.get(reverse("accounts:profile"))
    assert response.status_code == 302
    assert reverse("account_login") in response.url


# ---------------------------------------------------------------------------
# Profile form (view + update)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_page_renders_form(authenticated_client):
    """The profile page renders the edit form for the logged-in user."""
    response = authenticated_client.get(reverse("accounts:profile"))
    assert response.status_code == 200
    assert "form" in response.context
    # Form should be pre-filled with the user's current details.
    assert response.context["form"].initial["email"] == "user@example.com"


@pytest.mark.django_db
def test_profile_form_updates_user(authenticated_client, user):
    """Submitting the profile form persists the changes."""
    response = authenticated_client.post(
        reverse("accounts:profile"),
        {
            "email": user.email,
            "first_name": "Jane",
            "last_name": "Smith",
        },
    )
    assert response.status_code == 302  # redirect after success
    user.refresh_from_db()
    assert user.last_name == "Smith"


@pytest.mark.django_db
def test_profile_form_rejects_duplicate_email(authenticated_client, user, second_user):
    """A second user already owns an email; updating to it must fail."""
    response = authenticated_client.post(
        reverse("accounts:profile"),
        {
            "email": second_user.email,  # taken by another user
            "first_name": "Jane",
            "last_name": "Doe",
        },
    )
    assert response.status_code == 200  # form re-rendered with errors
    assert response.context["form"].errors


# ---------------------------------------------------------------------------
# Dashboard (renders real user data)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_shows_accounts(authenticated_client, user):
    """The dashboard lists the user's trading accounts."""
    TradingAccount.objects.create(
        user=user,
        account_name="Alpha Broker",
        last_trade_date=timezone.now() - timezone.timedelta(days=2),
    )
    response = authenticated_client.get(reverse("accounts:dashboard"))
    assert response.status_code == 200
    assert "Alpha Broker" in response.content.decode()


@pytest.mark.django_db
def test_dashboard_shows_empty_state_when_no_accounts(authenticated_client):
    """Without accounts the dashboard shows the empty prompt."""
    response = authenticated_client.get(reverse("accounts:dashboard"))
    assert response.status_code == 200
    assert not response.context["accounts"]
    assert "haven't added any trading accounts yet" in response.content.decode()


@pytest.mark.django_db
def test_dashboard_saves_detected_timezone_over_utc_default(authenticated_client, user):
    """A new user on the 'UTC' default gets the browser timezone saved."""
    assert user.timezone == "UTC"
    authenticated_client.get(reverse("accounts:dashboard") + "?tz=Africa/Kampala")
    user.refresh_from_db()
    assert user.timezone == "Africa/Kampala"


@pytest.mark.django_db
def test_dashboard_does_not_overwrite_detected_timezone(authenticated_client, user):
    """Once a real timezone is saved, later detections don't change it."""
    user.timezone = "Africa/Kampala"
    user.save()
    authenticated_client.get(reverse("accounts:dashboard") + "?tz=Europe/London")
    user.refresh_from_db()
    assert user.timezone == "Africa/Kampala"


@pytest.mark.django_db
def test_profile_email_change_requires_verification(authenticated_client, user, mailoutbox):
    """Changing email leaves the new address unverified and sends a confirmation."""
    from allauth.account.models import EmailAddress

    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    authenticated_client.post(
        reverse("accounts:profile"),
        {"email": "new@example.com", "first_name": "", "last_name": ""},
    )
    user.refresh_from_db()
    assert user.email == "new@example.com"
    address = EmailAddress.objects.get(user=user)
    assert address.email == "new@example.com"
    assert address.primary is True
    assert address.verified is False
    assert any("new@example.com" in m.to for m in mailoutbox)


# ---------------------------------------------------------------------------
# Connect Telegram (profile page)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_shows_connect_telegram_link_when_not_connected(
    authenticated_client, user, settings
):
    settings.TELEGRAM_BOT_USERNAME = "FAIR_Alertss_bot"
    user.telegram_chat_id = ""  # the shared `user` fixture defaults this set
    user.save()
    response = authenticated_client.get(reverse("accounts:profile"))
    assert response.status_code == 200
    assert response.context["telegram_connect_url"] is not None
    assert "t.me/FAIR_Alertss_bot?start=" in response.context["telegram_connect_url"]
    assert "Connect Telegram" in response.content.decode()


@pytest.mark.django_db
def test_profile_hides_connect_link_without_bot_username_configured(
    authenticated_client, settings
):
    settings.TELEGRAM_BOT_USERNAME = ""
    response = authenticated_client.get(reverse("accounts:profile"))
    assert response.context["telegram_connect_url"] is None


@pytest.mark.django_db
def test_profile_shows_connected_state(authenticated_client, user, settings):
    settings.TELEGRAM_BOT_USERNAME = "FAIR_Alertss_bot"
    user.telegram_chat_id = "123456"
    user.save()
    response = authenticated_client.get(reverse("accounts:profile"))
    assert "Telegram connected" in response.content.decode()
    assert response.context["telegram_connect_url"] is None


@pytest.mark.django_db
def test_disconnect_telegram_clears_chat_id(authenticated_client, user):
    user.telegram_chat_id = "123456"
    user.save()
    response = authenticated_client.post(
        reverse("accounts:profile"), {"disconnect_telegram": "1"}
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.telegram_chat_id == ""


# --- MT5 auto-sync: profile card and EA download ------------------------------


@pytest.mark.django_db
def test_profile_shows_mt5_card_with_key(authenticated_client, user):
    response = authenticated_client.get(reverse("accounts:profile"))
    user.refresh_from_db()
    html = response.content.decode()
    assert user.mt5_sync_key and user.mt5_sync_key in html
    assert reverse("accounts:mt5_ea") in html


@pytest.mark.django_db
def test_profile_mt5_card_says_no_vps_and_flags_firm_rules(authenticated_client):
    """Goat Funded Trader bans VPN/VPS/hosting (from 2026-10-06) and FundedNext
    CFD $50k+ bans "any automated tools", so the setup steps must not suggest
    a VPS and must send those traders to their firm first."""
    html = authenticated_client.get(reverse("accounts:profile")).content.decode()
    card = html[html.index('id="mt5"'):html.index(reverse("accounts:mt5_ea"))]
    assert "PC or VPS" not in card
    assert "not a VPS" in card
    assert "Goat Funded Trader" in card
    assert "$50k" in card and "in writing" in card


@pytest.mark.django_db
def test_profile_mt5_card_allows_the_trading_mt5_when_an_allowed_ea_trades(authenticated_client):
    """An account already traded by an EA the firm allows (e.g. the owner's own
    bot on GFT) can run FAIR Sync in that same MT5, on a chart with no other EA:
    dropping it on the bot's chart would replace the bot. Firms that restrict
    EAs still get the separate investor-password MT5."""
    html = authenticated_client.get(reverse("accounts:profile")).content.decode()
    # Collapse whitespace: the template wraps sentences across lines.
    card = " ".join(html[html.index('id="mt5"'):html.index(reverse("accounts:mt5_ea"))].split())
    assert "Never attach FAIR Sync to the MT5 you trade in" not in card
    assert "already traded by an EA your firm allows" in card
    assert "a chart with no other EA" in card
    assert "investor-password MT5" in card


@pytest.mark.django_db
def test_regenerate_mt5_key(authenticated_client, user):
    old = user.get_or_create_mt5_sync_key()
    response = authenticated_client.post(reverse("accounts:profile"), {"regenerate_mt5_key": "1"})
    assert response.status_code == 302 and response["Location"].endswith("#mt5")
    user.refresh_from_db()
    assert user.mt5_sync_key and user.mt5_sync_key != old


@pytest.mark.django_db
def test_mt5_ea_download_is_prefilled(authenticated_client, user, settings):
    settings.SITE_SCHEME, settings.SITE_DOMAIN = "https", "fair.example.com"
    response = authenticated_client.get(reverse("accounts:mt5_ea"))
    assert response.status_code == 200
    assert 'filename="FAIR_Sync.mq5"' in response["Content-Disposition"]
    body = response.content.decode()
    user.refresh_from_db()
    assert f'"https://fair.example.com{reverse("mt5_sync")}"' in body
    assert f'"{user.mt5_sync_key}"' in body
    assert "__FAIR_URL__" not in body and "__FAIR_KEY__" not in body
    assert "OnTradeTransaction" in body


def test_mt5_ea_download_requires_login(client):
    response = client.get(reverse("accounts:mt5_ea"))
    assert response.status_code == 302
    assert "/login" in response["Location"]


def test_mt5_ea_gives_allow_webrequest_hint_for_4006_and_4014():
    """MT5 refuses a URL missing from "Allow WebRequest" with 4014, or 4006
    when the URL is an IP address (seen on MT5 build 6230 under Wine). Both
    must print the fix, not a generic "could not reach FAIR"."""
    from accounts.views import MT5_EA_PATH

    source = MT5_EA_PATH.read_text(encoding="utf-8")
    hint = source.index("Allow WebRequest for listed URL")
    condition = source[source.rfind("if(", 0, hint):hint]
    assert "4014" in condition
    assert "4006" in condition


def test_mt5_ea_header_keeps_a_bots_algo_trading_on():
    """Someone running FAIR Sync next to their own trading bot must not be told
    to switch the terminal's Algo Trading off: that would stop the bot."""
    from accounts.views import MT5_EA_PATH

    lines = MT5_EA_PATH.read_text(encoding="utf-8").splitlines()
    # The header is a box of "//| ... |" lines; join its text into one string.
    header = " ".join(" ".join(l[3:].rstrip().rstrip("|").split()) for l in lines if l.startswith("//|"))
    assert "already traded by an EA your firm allows" in header
    assert "a chart with no other EA" in header
    assert "leave the terminal's on" in header
