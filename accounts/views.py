import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from allauth.account.models import EmailAddress
from django.core.cache import cache
from django.core.mail import send_mail
from trades.notifications import send_telegram_message
from trades.models import TradingAccount

from . import telegram_bot
from .calendar import build_ics
from .models import User
from .forms import ProfileForm

logger = logging.getLogger(__name__)


def home(request):
    """Public landing page."""
    return render(request, "home.html")


def privacy(request):
    """Public privacy policy page."""
    return render(request, "privacy.html")


def terms(request):
    """Public terms of service page."""
    return render(request, "terms.html")


def contact(request):
    """Public contact/support page."""
    return render(request, "contact.html")


@login_required
def dashboard(request):
    """User dashboard (shown after login).

    Shows the user's trading accounts and upcoming deadlines so they can act
    before accounts go inactive.
    """
    # Auto-detect timezone from the browser (sent via ?tz=) when needed.
    _save_detected_timezone(request)

    # Most urgent first; accounts already past their deadline go last.
    accounts = sorted(
        request.user.trading_accounts.select_related("user"),
        key=lambda a: (a.is_inactive, a.days_remaining, a.account_name.lower()),
    )
    return render(
        request,
        "dashboard.html",
        {
            "user": request.user,
            "accounts": accounts,
            "threshold": TradingAccount.INACTIVITY_THRESHOLD_DAYS,
        },
    )


def _save_detected_timezone(request) -> None:
    """Store the browser-detected timezone on the user (once) if provided."""
    tz = request.GET.get("tz") or request.POST.get("tz")
    if not tz:
        return
    user = request.user
    # New users start on the "UTC" default, so treat that as "not detected yet".
    if user.is_authenticated and user.timezone in ("", "UTC"):
        before = user.timezone
        user.set_timezone_from_js(tz)
        if user.timezone and user.timezone != before:
            user.save(update_fields=["timezone"])


@login_required
def profile(request):
    """User profile page: view and update contact details.

    Handles both GET (render the form) and POST (save the changes). When the
    email changes, allauth's ``EmailAddress`` record is updated too so the
    two stay in sync. A separate "disconnect_telegram" POST action (its own
    button, not part of ProfileForm) clears a connected Telegram chat.
    """
    if request.method == "POST" and "regenerate_calendar" in request.POST:
        request.user.regenerate_calendar_token()
        messages.success(
            request,
            "New calendar link created. The old link no longer works — "
            "re-subscribe in your calendar app with the new one.",
        )
        return redirect("accounts:profile")

    if request.method == "POST" and "regenerate_mt5_key" in request.POST:
        request.user.regenerate_mt5_sync_key()
        messages.success(
            request,
            "New MT5 sync key created. EAs using the old key stop syncing — "
            "download the FAIR Sync EA again and replace it in MT5.",
        )
        return redirect(reverse("accounts:profile") + "#mt5")

    if request.method == "POST" and "disconnect_telegram" in request.POST:
        request.user.telegram_chat_id = ""
        request.user.save(update_fields=["telegram_chat_id"])
        messages.success(request, "Telegram disconnected.")
        return redirect("accounts:profile")

    if request.method == "POST":
        # Read the current email before binding: form validation writes the
        # submitted values onto request.user.
        old_email = request.user.email
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            user = form.save()

            # When the address changes, the new one must be verified: replace
            # allauth's records with an unverified address and send a
            # confirmation link to it.
            if user.email.lower() != old_email.lower():
                new_email = user.email
                EmailAddress.objects.filter(user=user).exclude(
                    email__iexact=new_email
                ).delete()
                address = EmailAddress.objects.add_email(
                    request, user, new_email, confirm=True
                )
                address.set_as_primary()
                messages.info(
                    request,
                    f"We sent a confirmation link to {new_email}. "
                    "Please verify your new email address.",
                )

            messages.success(request, "Your profile was updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    telegram_connect_url = None
    if not request.user.telegram_chat_id and settings.TELEGRAM_BOT_USERNAME:
        token = request.user.get_or_create_telegram_link_token()
        telegram_connect_url = (
            f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"
        )

    return render(
        request,
        "account/profile.html",
        {
            "form": form,
            "user": request.user,
            "telegram_connect_url": telegram_connect_url,
            "calendar_url": request.build_absolute_uri(
                reverse("accounts:calendar_feed", args=[request.user.get_or_create_calendar_token()])
            ),
            "mt5_sync_key": request.user.get_or_create_mt5_sync_key(),
        },
    )


#: The FAIR Sync Expert Advisor source; its two placeholders are filled in
#: per user by :func:`mt5_ea`.
MT5_EA_PATH = settings.BASE_DIR / "mt5" / "FAIR_Sync.mq5"


@login_required
def mt5_ea(request):
    """Download FAIR_Sync.mq5 with this site's sync URL and the user's sync
    key pre-filled, so nothing has to be typed into MT5."""
    sync_url = f"{settings.SITE_SCHEME}://{settings.SITE_DOMAIN}{reverse('mt5_sync')}"
    source = MT5_EA_PATH.read_text(encoding="utf-8")
    body = source.replace("__FAIR_URL__", sync_url).replace(
        "__FAIR_KEY__", request.user.get_or_create_mt5_sync_key()
    )
    response = HttpResponse(body, content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="FAIR_Sync.mq5"'
    response["Cache-Control"] = "private, no-store"
    return response


def calendar_feed(request, token):
    """Private .ics feed of the user's deadlines (the token is the secret)."""
    user = User.objects.filter(calendar_token=token).first() if token else None
    if user is None:
        raise Http404("Unknown calendar link.")
    response = HttpResponse(build_ics(user), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="fair-deadlines.ics"'
    response["Cache-Control"] = "private, max-age=900"
    return response


#: Seconds a user must wait between "Send me a test reminder" clicks.
TEST_REMINDER_COOLDOWN = 5 * 60


@login_required
@require_POST
def test_reminder(request):
    """Send a test message on each of the user's channels and report the
    outcome per channel, so delivery problems (e.g. SMTP misconfiguration,
    a blocked bot) are visible to the user right away."""
    user = request.user
    cache_key = f"fair:test-reminder:{user.pk}"
    if not cache.add(cache_key, True, TEST_REMINDER_COOLDOWN):
        messages.warning(request, "Test reminder already sent — please wait a few minutes before trying again.")
        return redirect("accounts:profile")

    text = (
        "✅ This is a test reminder from FAIR. If you can read it, reminders "
        "will reach you on this channel."
    )
    try:
        send_mail("FAIR test reminder", text, settings.DEFAULT_FROM_EMAIL, [user.email])
        messages.success(request, f"Email: test sent to {user.email}. Check your inbox (and spam folder).")
    except Exception as exc:  # noqa: BLE001 - report to the user
        logger.exception("[test reminder] Email to %s failed.", user.email)
        messages.error(request, f"Email: sending failed — {type(exc).__name__}: {exc}")

    if user.telegram_chat_id:
        try:
            if send_telegram_message(user.telegram_chat_id, text):
                messages.success(request, "Telegram: test sent. Check the FAIR bot chat.")
            else:
                messages.warning(request, "Telegram: not configured on this server.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("[test reminder] Telegram to chat %s failed.", user.telegram_chat_id)
            messages.error(request, f"Telegram: sending failed — {type(exc).__name__}: {exc}")
    else:
        messages.info(request, "Telegram: not connected (connect it below to get reminders there too).")

    return redirect("accounts:profile")


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Receives updates from Telegram's webhook (see the set_telegram_webhook
    management command) and hands them to :mod:`accounts.telegram_bot`.

    Verifies the shared secret header. Always returns 200 to genuine calls
    (Telegram retries on non-2xx) — problems are logged, not raised.
    """
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
        return HttpResponseForbidden("Invalid secret token")

    try:
        update = json.loads(request.body or b"{}")
    except (TypeError, ValueError):
        logger.warning("[telegram webhook] Ignoring malformed update body.")
        return HttpResponse(status=200)

    try:
        telegram_bot.handle_update(update if isinstance(update, dict) else {})
    except Exception:  # noqa: BLE001 - never 500 back to Telegram
        logger.exception("[telegram webhook] Failed to handle update %s.", update.get("update_id") if isinstance(update, dict) else "?")
    return HttpResponse(status=200)
