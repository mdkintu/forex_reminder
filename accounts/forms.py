from django import forms

from trades.forms import DayListField, _default_days_text

from .models import User


class ProfileForm(forms.ModelForm):
    """Form for a user to update their contact details, email and default
    reminder days."""

    reminder_days_left = DayListField(
        label="Default reminders (days left before the deadline)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reminder_days_left"].help_text = (
            "Used by accounts without their own list. 0 = the deadline day. "
            f"Leave blank for the site default ({_default_days_text()})."
        )

    class Meta:
        model = User
        # telegram_chat_id is deliberately not here: it's set via the
        # "Connect Telegram" deep-link flow (accounts.views.telegram_webhook),
        # not typed in by hand — see templates/account/profile.html.
        # phone_number is also left out: it exists solely for WhatsApp
        # reminders, which aren't wired up to a real provider yet.
        fields = [
            "email",
            "first_name",
            "last_name",
            "reminder_days_left",
        ]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "you@fair.tergym.com"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "First name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Last name"}
            ),
        }

