from django import forms

from .models import User


class ProfileForm(forms.ModelForm):
    """Form for a user to update their contact details and email."""

    class Meta:
        model = User
        # telegram_chat_id is deliberately not here: it's set via the
        # "Connect Telegram" deep-link flow (accounts.views.telegram_webhook),
        # not typed in by hand — see templates/account/profile.html.
        fields = [
            "email",
            "first_name",
            "last_name",
            "phone_number",
        ]
        widgets = {
            "email": forms.EmailInput(
                attrs={"class": "form-control", "placeholder": "you@example.com"}
            ),
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "First name"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Last name"}
            ),
            "phone_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "+15551234567 (E.164, used for WhatsApp)",
                }
            ),
        }

