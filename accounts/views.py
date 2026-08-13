from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from allauth.account.models import EmailAddress
from trades.models import TradingAccount

from .forms import ProfileForm


def home(request):
    """Public landing page."""
    return render(request, "home.html")


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
    if user.is_authenticated and not user.timezone:
        user.set_timezone_from_js(tz)
        if user.timezone:
            user.save(update_fields=["timezone"])


@login_required
def profile(request):
    """User profile page: view and update contact details.

    Handles both GET (render the form) and POST (save the changes). When the
    email changes, allauth's ``EmailAddress`` record is updated too so the
    two stay in sync.
    """
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            old_email = request.user.email
            user = form.save()

            # Keep allauth's email records in sync when the address changes.
            if user.email != old_email:
                EmailAddress.objects.filter(user=user).update(
                    email=user.email, verified=True, primary=True
                )

            messages.success(request, "Your profile was updated.")
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=request.user)

    return render(request, "account/profile.html", {"form": form, "user": request.user})

