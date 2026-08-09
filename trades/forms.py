from django import forms

from .models import TradingAccount


class TradingAccountForm(forms.ModelForm):
    """Form for creating/editing a user's trading account."""

    last_trade_date = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"}
        ),
        help_text="Date/time of the most recent trade on this account.",
    )

    class Meta:
        model = TradingAccount
        fields = [
            "account_name",
            "broker",
            "last_trade_date",
            "notify_email",
            "notify_whatsapp",
            "notify_telegram",
        ]
        widgets = {
            "account_name": forms.TextInput(attrs={"class": "form-control"}),
            "broker": forms.TextInput(attrs={"class": "form-control"}),
        }
