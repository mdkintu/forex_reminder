from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from allauth.account.models import EmailAddress
from trades.models import TradingAccount

from .forms import ProfileForm


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
    two stay in sync.
    """
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

    return render(request, "account/profile.html", {"form": form, "user": request.user})

