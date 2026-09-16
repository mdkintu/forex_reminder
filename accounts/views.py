import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from allauth.account.models import EmailAddress
from trades.models import TradingAccount
from trades.notifications import send_telegram_message

from .forms import ProfileForm
from .models import User

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

    accounts = request.user.trading_accounts.order_by("last_trade_date")
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
        },
    )


@csrf_exempt
@require_POST
def telegram_webhook(request):
    """Receives updates from Telegram's webhook (see the set_telegram_webhook
    management command).

    Handles the ``/start <token>`` message the "Connect Telegram" deep link
    sends: resolves which user the token belongs to, saves their chat id so
    reminders can reach them, and confirms in the chat. Always returns 200
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

    message = update.get("message") or update.get("edited_message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text.startswith("/start"):
        return HttpResponse(status=200)

    token = text[len("/start"):].strip()
    user = User.resolve_telegram_link_token(token)

    if user is None:
        _try_send_telegram(
            chat_id,
            "This link has expired or isn't valid. Go back to your FAIR "
            "profile page and tap “Connect Telegram” again.",
        )
        return HttpResponse(status=200)

    # Save first: the connection itself must not be lost even if the
    # confirmation reply below fails to send (network blip, Telegram API
    # error, etc.) — a retried webhook delivery would otherwise find the
    # token already cleared and wrongly report it as expired.
    user.telegram_chat_id = str(chat_id)
    user.save(update_fields=["telegram_chat_id"])
    user.clear_telegram_link_token()

    logger.info("[telegram webhook] Connected chat %s to user %s.", chat_id, user.email)
    _try_send_telegram(
        chat_id,
        "✅ Telegram connected! You'll receive FAIR inactivity reminders here.",
    )
    return HttpResponse(status=200)


def _try_send_telegram(chat_id, text) -> None:
    """send_telegram_message, but never raise — a failed reply here must not
    turn into a 500 back to Telegram (which would just retry the update)."""
    try:
        send_telegram_message(chat_id, text)
    except Exception:  # noqa: BLE001 - log and continue, see docstring
        logger.exception("[telegram webhook] Failed to reply to chat %s.", chat_id)

