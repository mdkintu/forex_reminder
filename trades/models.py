from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone


def validate_reminder_days(value):
    """Reject an empty or non-integer reminder-day list."""
    if not isinstance(value, list) or not value:
        raise ValidationError(
            "Reminder day list must be a non-empty list of integers."
        )
    for day in value:
        if not isinstance(day, int) or day < 1 or day > 365:
            raise ValidationError(
                "Each reminder day must be an integer between 1 and 365."
            )


class ReminderSchedule(models.Model):
    """Global configuration of the reminder day numbers.

    The ``day_list`` holds the numbers of days after the last trade on which
    a reminder is sent. It is configurable interactively (keyboard input,
    multiple values) through the ``set_reminder_days`` management command.
    """

    #: Default day numbers used if no schedule row exists yet.
    DEFAULT_DAYS = [10, 15, 25, 26, 27, 28, 29, 30]

    day_list = models.JSONField(
        default=list,
        validators=[validate_reminder_days],
        help_text="List of day numbers (after last trade) on which to send reminders.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reminder schedule"
        verbose_name_plural = "Reminder schedules"

    def __str__(self):
        return ", ".join(str(d) for d in self.days())

    @classmethod
    def get(cls):
        """Return the first schedule row (unsaved default if none exists)."""
        obj = cls.objects.first()
        if obj is None:
            obj = ReminderSchedule(day_list=ReminderSchedule.DEFAULT_DAYS)
        return obj

    def days(self):
        """The reminder day numbers as a tuple (never empty)."""
        return tuple(self.day_list or ReminderSchedule.DEFAULT_DAYS)

    def save(self, *args, **kwargs):
        # Keep only the first row so the global schedule stays a singleton.
        if self.pk is None and ReminderSchedule.objects.exists():
            return
        super().save(*args, **kwargs)


class TradingAccount(models.Model):
    """A user's forex trading account being monitored for inactivity."""

    INACTIVITY_THRESHOLD_DAYS = 30  # reminder target

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trading_accounts",
    )
    account_name = models.CharField(max_length=100)
    account_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="The account number for this trading account (e.g. brokerage account number).",
    )
    broker = models.CharField(max_length=100, blank=True)
    last_trade_date = models.DateTimeField(default=timezone.now)
    notify_email = models.BooleanField(default=True)
    notify_whatsapp = models.BooleanField(default=False)
    notify_telegram = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["account_name"]

    def __str__(self):
        return self.account_name

    def get_absolute_url(self):
        return reverse("trades:detail", kwargs={"pk": self.pk})

    @property
    def days_since_last_trade(self):
        """Whole days elapsed since the last trade, in the user's timezone.

        Computing this in the owner's local timezone (rather than UTC) makes
        the "days" line up with the user's calendar day, which matters for
        global users. Falls back to UTC if the user has no timezone set.
        """
        local_now = timezone.now().astimezone(self.user.get_timezone())
        local_last = timezone.localtime(
            self.last_trade_date, self.user.get_timezone()
        )
        return max(0, (local_now.date() - local_last.date()).days)

    @property
    def reminder_days(self):
        """Ordered day numbers (after last trade) on which to send reminders."""
        return ReminderSchedule.get().days()

    @property
    def days_remaining(self):
        """Days left before reaching the 30-day inactivity threshold."""
        return max(0, self.INACTIVITY_THRESHOLD_DAYS - self.days_since_last_trade)

    @property
    def is_inactive(self):
        """True when the account has crossed the inactivity threshold."""
        return self.days_since_last_trade >= self.INACTIVITY_THRESHOLD_DAYS

    @property
    def deadline(self):
        """The datetime at which the account becomes inactive (last trade + 30 days)."""
        return self.last_trade_date + timezone.timedelta(
            days=self.INACTIVITY_THRESHOLD_DAYS
        )

    def deadline_iso(self):
        """JS-friendly ISO 8601 timestamp of the inactivity deadline."""
        return self.deadline.isoformat()


class ReminderHistory(models.Model):
    """A record of an inactivity reminder sent for an account."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        TELEGRAM = "telegram", "Telegram"

    account = models.ForeignKey(
        TradingAccount,
        on_delete=models.CASCADE,
        related_name="reminders",
    )
    day_number = models.PositiveIntegerField(
        help_text="Days after the last trade when the reminder was sent."
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    status = models.CharField(max_length=20, default="sent")
    # The local hour (0-23) this reminder was intended for, so the two daily
    # delivery slots (e.g. 9 AM and 2 PM) are each recorded separately.
    slot_hour = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "day_number", "channel", "slot_hour"],
                name="unique_reminder_per_account_day_channel_slot",
            )
        ]
        ordering = ["-sent_at"]

    def __str__(self):
        return (
            f"{self.account} — day {self.day_number} via "
            f"{self.get_channel_display()} ({self.status})"
        )
