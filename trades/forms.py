from django import forms

from .daylists import MAX_DAY, MIN_DAY, parse_day_list
from .models import ReminderSchedule, TradingAccount


def _default_days_text():
    """The site-wide reminder days as text, e.g. "20, 15, 5, 3, 1, 0"."""
    return ", ".join(str(d) for d in ReminderSchedule.get().days_left_list())


class DayListField(forms.CharField):
    """A list of "days left" typed as text, e.g. "20, 10, 3, 1, 0".

    Cleans to a list of ints (largest first), or None when left blank
    (meaning "inherit the default").
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault(
            "widget", forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 20, 10, 3, 1, 0"})
        )
        super().__init__(**kwargs)

    def prepare_value(self, value):
        if isinstance(value, (list, tuple)):
            return ", ".join(str(d) for d in value)
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return None
        days, invalid = parse_day_list(value)
        if invalid:
            raise forms.ValidationError(
                "Use whole numbers separated by commas — not understood: %(bad)s",
                params={"bad": ", ".join(invalid)},
            )
        if any(d < MIN_DAY or d > MAX_DAY for d in days):
            raise forms.ValidationError(f"Each day must be between {MIN_DAY} and {MAX_DAY}.")
        return days


class TradingAccountForm(forms.ModelForm):
    """Form for creating/editing a user's trading account."""

    last_trade_date = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"}
        ),
        help_text="Date/time of the most recent trade on this account.",
    )
    reminder_days_left = DayListField(
        label="Reminders (days left)",
        help_text="Days before the deadline to remind you (0 = deadline day). "
        "Leave blank to use your profile default.",
    )

    class Meta:
        model = TradingAccount
        # notify_whatsapp is deliberately not here: WhatsApp reminders aren't
        # wired up to a real provider yet, so the toggle is hidden rather
        # than offered as if it worked. See trades/models.py.
        fields = [
            "account_name",
            "account_number",
            "broker",
            "last_trade_date",
            "inactivity_days",
            "reminder_days_left",
            "notify_email",
            "notify_telegram",
        ]
        widgets = {
            "account_name": forms.TextInput(attrs={"class": "form-control"}),
            "account_number": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. 80812345"}
            ),
            "broker": forms.TextInput(attrs={"class": "form-control"}),
            "inactivity_days": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": MAX_DAY, "list": "inactivity-presets"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Blank keeps the account's current limit (30 for a new account).
        self.fields["inactivity_days"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("inactivity_days") is None and "inactivity_days" not in self.errors:
            cleaned["inactivity_days"] = (
                self.instance.inactivity_days or TradingAccount.INACTIVITY_THRESHOLD_DAYS
            )
        days, limit = cleaned.get("reminder_days_left"), cleaned.get("inactivity_days")
        if days and limit and any(d > limit for d in days):
            self.add_error(
                "reminder_days_left",
                f"Every value must be at most the inactivity limit ({limit} days).",
            )
        return cleaned
