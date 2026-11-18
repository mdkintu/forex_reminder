from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

# validate_reminder_days is imported here too because migration 0002
# references it as trades.models.validate_reminder_days.
from .daylists import (  # noqa: F401
    MAX_DAY,
    days_left_to_days_since,
    validate_optional_reminder_days,
    validate_reminder_days,
)


class ReminderSchedule(models.Model):
    """Site-wide default reminder days, as "days left before the deadline".

    ``days_left`` holds day counts before an account's inactivity deadline on
    which a reminder is sent (0 = the deadline day itself). Each account
    converts them using its own ``inactivity_days`` limit, so one list works
    for 14-, 21- and 30-day accounts. Users and accounts can override it.
    Set it in the admin or with the ``set_reminder_days`` command.
    """

    #: Default if no schedule row exists yet. For a 30-day account this is
    #: days 10, 15 and 25–30 after the last trade. 0 (the deadline day) is the
    #: final, most urgent reminder — see the day-vs-deadline note in
    #: trades.tasks.evaluate_account for why it is compared by calendar day.
    DEFAULT_DAYS_LEFT = [20, 15, 5, 4, 3, 2, 1, 0]

    days_left = models.JSONField(
        default=list,
        validators=[validate_reminder_days],
        help_text="Days before the inactivity deadline on which to send reminders "
        "(0 = deadline day), e.g. [20, 15, 5, 3, 1, 0].",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Reminder schedule"
        verbose_name_plural = "Reminder schedules"

    def __str__(self):
        return "Days left: " + ", ".join(str(d) for d in self.days_left_list())

    @classmethod
    def get(cls):
        """Return the first schedule row (unsaved default if none exists)."""
        obj = cls.objects.first()
        if obj is None:
            obj = ReminderSchedule(days_left=list(ReminderSchedule.DEFAULT_DAYS_LEFT))
        return obj

    def days_left_list(self):
        """The "days left" values as a tuple, largest first (never empty)."""
        return tuple(sorted(self.days_left or ReminderSchedule.DEFAULT_DAYS_LEFT, reverse=True))

    def save(self, *args, **kwargs):
        # Keep the global schedule a singleton: saving a new row updates the
        # existing one instead of being silently ignored.
        if self.pk is None:
            existing = ReminderSchedule.objects.first()
            if existing is not None:
                self.pk = existing.pk
                kwargs["force_insert"] = False
        super().save(*args, **kwargs)


class TradingAccount(models.Model):
    """A user's forex trading account being monitored for inactivity."""

    #: Default inactivity limit (most prop firms close accounts after 30 days
    #: without a trade; some use 14 or 21). Each account sets its own.
    INACTIVITY_THRESHOLD_DAYS = 30

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
    inactivity_days = models.PositiveSmallIntegerField(
        default=INACTIVITY_THRESHOLD_DAYS,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_DAY)],
        help_text="Days without a trade after which your prop firm closes the account.",
    )
    #: Per-account override of the reminder days ("days left"); None = use the
    #: owner's default, then the site-wide ReminderSchedule.
    reminder_days_left = models.JSONField(
        null=True, blank=True, validators=[validate_optional_reminder_days]
    )

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

    def mark_traded(self, when=None):
        """Record a trade now (or at ``when``), restarting the countdown.

        Reminder de-duplication is per cycle (ReminderHistory.cycle_start), so
        the new last_trade_date automatically starts a fresh reminder cycle.
        """
        self.last_trade_date = when or timezone.now()
        self.save(update_fields=["last_trade_date", "updated_at"])

    def reminder_days_left_values(self, global_days_left=None):
        """Effective "days left" reminder values: this account's override, else
        the owner's default, else the site-wide schedule (``global_days_left``
        if given, to avoid a query per account), else the built-in default."""
        if self.reminder_days_left:
            return tuple(sorted(self.reminder_days_left, reverse=True))
        if self.user.reminder_days_left:
            return tuple(sorted(self.user.reminder_days_left, reverse=True))
        if global_days_left is None:
            global_days_left = ReminderSchedule.get().days_left_list()
        return tuple(global_days_left)

    def reminder_days(self, global_days_left=None):
        """Days since the last trade on which reminders fire for this account."""
        return days_left_to_days_since(
            self.reminder_days_left_values(global_days_left), self.inactivity_days
        )

    @property
    def days_remaining(self):
        """Days left before reaching this account's inactivity limit."""
        return max(0, self.inactivity_days - self.days_since_last_trade)

    def next_reminder_datetime(self):
        """The next datetime a reminder will be sent (user's local time), or None.

        Algorithm (per the delivery rules):
        * On a schedule day a reminder goes out at each configured local hour
          (normally 09:00 and 14:00), but a later-in-day slot is skipped if the
          user placed a trade after the previous slot that day.
        * If today is a schedule day and a send hour is still ahead, that is the
          next reminder.
        * Otherwise the next reminder is the next upcoming schedule day at its
          first send hour.
        * Returns None when there is no upcoming reminder (e.g. the account is
          already inactive / past the schedule).
        """
        send_hours = sorted(set(getattr(settings, "REMINDER_SEND_HOURS", [9, 14])))
        if not send_hours:
            return None
        schedule = sorted(self.reminder_days())
        if not schedule:
            return None

        tz = self.user.get_timezone()
        now_local = timezone.localtime(timezone.now(), tz)
        days_since = self.days_since_last_trade
        today = now_local.date()

        def traded_after(previous_hour):
            """True if the user last traded after `previous_hour` today (local)."""
            prev_dt = now_local.replace(
                hour=previous_hour, minute=0, second=0, microsecond=0
            )
            return timezone.localtime(self.last_trade_date, tz) > prev_dt

        # Helper to build a send datetime for a given date + hour.
        def at_hour(d, hour):
            return timezone.make_aware(
                timezone.datetime(d.year, d.month, d.day, hour, 0, 0),
                tz,
            )

        # Case 1: today is a schedule day -> next slot today, if any.
        # Compared by calendar day (days_since), not the exact deadline
        # instant: deadline is last_trade_date + 30 days to the second, tied
        # to the original trade's time-of-day, while days_since is a plain
        # calendar-date difference. Comparing a slot time against the exact
        # deadline would wrongly hide the day-30 reminder whenever the last
        # trade happened earlier in the day than the send hours.
        if days_since in schedule and days_since <= self.inactivity_days:
            for hour in send_hours:
                slot_dt = at_hour(today, hour)
                if slot_dt <= now_local:
                    continue
                # Skip the slot only if a prior slot fired and the user traded
                # since that prior slot (later-in-day skip rule).
                prior = [h for h in send_hours if h < hour]
                if prior and traded_after(max(prior)):
                    continue
                return slot_dt
            # All today's slots are past -> fall through to next schedule day.

        # Case 2: find the next schedule day strictly greater than today.
        future = [d for d in schedule if d > days_since]
        if future:
            next_day = min(future)
            if next_day <= self.inactivity_days:
                return at_hour(
                    today + timezone.timedelta(days=next_day - days_since), send_hours[0]
                )

        # No next schedule day (e.g. past the last mark / inactive).
        return None

    @property
    def time_until_next_reminder(self):
        """A timedelta (or None) until the next reminder fires."""
        nxt = self.next_reminder_datetime()
        if nxt is None:
            return None
        return nxt - timezone.now()

    @property
    def next_reminder_label(self):
        """A human-friendly label for the time until the next reminder.

        E.g. "today at 2:00 PM", "in 2 days (10-day mark)", or "no upcoming
        reminder". Time is shown in the user's local timezone.
        """
        nxt = self.next_reminder_datetime()
        if nxt is None:
            return "No upcoming reminder"
        tz = self.user.get_timezone()
        nxt_local = nxt.astimezone(tz)
        delta = nxt_local - timezone.localtime(timezone.now(), tz)
        total_days = delta.days
        total_hours = delta.seconds // 3600

        when = nxt_local.strftime("%I:%M %p").lstrip("0")
        if total_days <= 0 and total_hours < 1:
            # Under an hour away.
            minutes = max(1, delta.seconds // 60)
            return f"In {minutes} min ({when})"
        if total_days <= 0:
            return f"Today at {when}"
        if total_days == 1:
            return f"Tomorrow at {when}"
        return f"In {total_days} days at {when}"

    def next_reminder_iso(self):
        """ISO 8601 timestamp of the next reminder, or an empty string if none.

        JS-friendly value for a live countdown (data-reminder attribute).
        """
        nxt = self.next_reminder_datetime()
        if nxt is None:
            return ""
        return nxt.isoformat()

    @property
    def is_inactive(self):
        """True when the account has crossed the inactivity threshold."""
        return self.days_since_last_trade >= self.inactivity_days

    @property
    def deadline(self):
        """When the account becomes inactive (last trade + its inactivity limit)."""
        return self.last_trade_date + timezone.timedelta(days=self.inactivity_days)

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
    class Status(models.TextChoices):
        #: Created and being sent right now (also left behind if a worker
        #: crashed mid-send; such rows are not retried, to avoid duplicates).
        PENDING = "pending", "Sending"
        SENT = "sent", "Sent"
        #: Channel not configured (no credentials / no chat id). Final.
        SKIPPED = "skipped", "Skipped"
        #: Sending raised an error; retried on later runs of the same slot,
        #: up to settings.REMINDER_MAX_ATTEMPTS attempts.
        FAILED = "failed", "Failed"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SENT)
    attempts = models.PositiveSmallIntegerField(default=1)
    #: The last delivery error (for failed rows).
    error = models.TextField(blank=True)
    #: Sent late, for a reminder day that passed without any delivery.
    catch_up = models.BooleanField(default=False)
    # The local hour (0-23) this reminder was intended for, so the two daily
    # delivery slots (e.g. 9 AM and 2 PM) are each recorded separately.
    slot_hour = models.PositiveSmallIntegerField(default=0)
    # The account's last_trade_date when this reminder was sent, i.e. which
    # inactivity cycle it belongs to. A new trade starts a new cycle, so its
    # day-N reminders must not be blocked by the previous cycle's. NULL for
    # rows from past cycles recorded before this field existed.
    cycle_start = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["account", "cycle_start", "day_number", "channel", "slot_hour"],
                name="unique_reminder_per_cycle_day_channel_slot",
            )
        ]
        ordering = ["-sent_at"]

    def __str__(self):
        return (
            f"{self.account} — day {self.day_number} via "
            f"{self.get_channel_display()} ({self.status})"
        )


class ReminderRun(models.Model):
    """One execution of the reminder job (cron or Celery), for monitoring.

    Written at the end of every real (non-dry) run so the daily admin report
    and the admin can show whether the job is actually running and what it
    did. A missing run for hours means cron is broken.
    """

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    checked = models.PositiveIntegerField(default=0)
    sent = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    #: Set on the run during which the daily admin report went out, so the
    #: report is sent at most once per day.
    report_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-finished_at"]

    def __str__(self):
        return (
            f"{self.finished_at:%Y-%m-%d %H:%M} — checked {self.checked}, "
            f"sent {self.sent}, skipped {self.skipped}, failed {self.failed}"
        )
