from django import forms

from .models import User


class ProfileForm(forms.ModelForm):
    """Form for a user to update their contact details and email."""

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

