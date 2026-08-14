from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Admin configuration for the custom email-based user model."""

    ordering = ["email"]
    list_display = [
        "email",
        "first_name",
        "last_name",
        "timezone",
        "is_staff",
        "is_active",
    ]
    search_fields = ["email", "first_name", "last_name", "phone_number", "telegram_chat_id"]
    list_filter = ["is_staff", "is_active", "is_superuser"]

    # Remove the username field from the fieldsets / add the email.
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {
            "fields": (
                "first_name",
                "last_name",
                "phone_number",
                "telegram_chat_id",
                "timezone",
            )
        }),
        ("Permissions", {
            "fields": (
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            ),
        }),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2"),
        }),
    )
