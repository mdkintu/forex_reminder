"""Helpers for reminder day lists ("days left before the deadline").

A reminder schedule is a list of day counts *before* an account's inactivity
deadline, e.g. ``[20, 15, 5, 3, 1, 0]`` (0 = the deadline day itself). Each
account converts it to "days since last trade" with its own limit, so the same
list works for 14-, 21- and 30-day prop-firm rules.
"""

from django.core.exceptions import ValidationError

#: Smallest / largest value allowed in a day list.
MIN_DAY, MAX_DAY = 0, 365


def parse_day_list(values):
    """Parse ``"20, 15 3"`` (or an iterable of strings/ints) into day numbers.

    Returns ``(days, invalid)``: the valid integers, de-duplicated and sorted
    descending, and the tokens that were not integers.
    """
    if isinstance(values, str):
        values = [values]
    days, invalid = set(), []
    for value in values:
        for token in str(value).replace(",", " ").split():
            try:
                days.add(int(token))
            except ValueError:
                invalid.append(token)
    return sorted(days, reverse=True), invalid


def days_after_to_days_left(days_after, limit=30):
    """Convert old-style "days since last trade" values to "days left"."""
    return sorted({limit - d for d in days_after if 0 <= d <= limit}, reverse=True)


def days_left_to_days_since(days_left, limit):
    """Convert "days left" values to the "days since last trade" they fall on
    for an account with an inactivity ``limit`` (values beyond it are dropped)."""
    return tuple(sorted({limit - d for d in days_left if 0 <= d <= limit}))


def validate_reminder_days(value):
    """Reject an empty or invalid reminder-day list ("days left", 0–365)."""
    if not isinstance(value, list) or not value:
        raise ValidationError(
            "Reminder day list must be a non-empty list of integers."
        )
    for day in value:
        if not isinstance(day, int) or isinstance(day, bool) or day < MIN_DAY or day > MAX_DAY:
            raise ValidationError(
                f"Each reminder day must be a whole number between {MIN_DAY} and {MAX_DAY}."
            )


def validate_optional_reminder_days(value):
    """Like validate_reminder_days, but None/empty means "inherit"."""
    if value in (None, []):
        return
    validate_reminder_days(value)
