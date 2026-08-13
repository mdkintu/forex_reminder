from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Manager for the custom email-based user model (no username)."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a user with the given email and password."""
        if not email:
            raise ValueError("The given email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular user with the given email and password."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model using email as the unique identifier."""

    username = None  # Remove the username field entirely

    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True)
    telegram_chat_id = models.CharField(max_length=100, blank=True)
    # IANA timezone name (e.g. "Africa/Nairobi", "America/New_York"). Auto
    # detected from the user's browser on first login, with a manual override.
    # Used to compute "days since last trade" in the user's local timezone so
    # inactivity reminders land on the right day for global users.
    timezone = models.CharField(max_length=64, blank=True, default="UTC")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # Email is already required via USERNAME_FIELD

    objects = UserManager()

    def __str__(self):
        return self.email

    def get_timezone(self):
        """Return a usable ``tzinfo`` for the user's timezone (fallback UTC)."""
        import zoneinfo

        try:
            return zoneinfo.ZoneInfo(self.timezone or "UTC")
        except (zoneinfo.ZoneInfoNotFoundError, ValueError):
            return zoneinfo.ZoneInfo("UTC")

    def set_timezone_from_js(self, value):
        """Safely store a browser-detected IANA timezone name."""
        import zoneinfo

        if not value:
            return
        try:
            zoneinfo.ZoneInfo(value)  # raises if invalid
            if self.timezone != value:
                self.timezone = value
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError):
            pass  # ignore junk from the client
