"""Phase 3: per-account inactivity limits; reminder days counted as "days left"."""

from datetime import timedelta
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

import trades.tasks as tasks
from accounts.forms import ProfileForm
from trades.daylists import days_after_to_days_left, parse_day_list
from trades.forms import TradingAccountForm
from trades.models import ReminderHistory, ReminderSchedule, TradingAccount


def _acct(user, days_ago=0, **kw):
    return TradingAccount.objects.create(
        user=user,
        account_name=kw.pop("name", "Acct"),
        last_trade_date=timezone.now() - timedelta(days=days_ago),
        notify_email=True,
        **kw,
    )


# --- helpers ---------------------------------------------------------------


def test_parse_day_list():
    assert parse_day_list("20, 15 3,3 x 0") == ([20, 15, 3, 0], ["x"])
    assert parse_day_list(["5", 7]) == ([7, 5], [])


def test_days_after_to_days_left():
    assert days_after_to_days_left([10, 15, 20]) == [20, 15, 10]
    assert days_after_to_days_left([10, 15, 25, 26, 27, 28, 29, 30]) == [20, 15, 5, 4, 3, 2, 1, 0]
    assert days_after_to_days_left([31, 10], limit=30) == [20]


# --- resolver: account > user > global > default --------------------------


@pytest.mark.django_db
def test_days_left_resolution_order(user):
    acct = _acct(user)
    assert acct.reminder_days_left_values() == tuple(ReminderSchedule.DEFAULT_DAYS_LEFT)

    ReminderSchedule.objects.create(days_left=[10, 1])
    assert acct.reminder_days_left_values() == (10, 1)

    user.reminder_days_left = [7, 2]
    user.save()
    acct.refresh_from_db()
    assert acct.reminder_days_left_values() == (7, 2)

    acct.reminder_days_left = [3]
    acct.save()
    assert acct.reminder_days_left_values() == (3,)


@pytest.mark.django_db
def test_days_left_converted_per_limit(user):
    thirty = _acct(user)
    fourteen = _acct(user, inactivity_days=14)
    # Default [20, 15, 5, 4, 3, 2, 1, 0]
    assert thirty.reminder_days() == (10, 15, 25, 26, 27, 28, 29, 30)
    assert fourteen.reminder_days() == (9, 10, 11, 12, 13, 14)  # 20/15 left don't fit


# --- per-account limit drives the countdown --------------------------------


@pytest.mark.django_db
def test_limit_drives_deadline_and_days_left(user):
    acct = _acct(user, days_ago=10, inactivity_days=14)
    assert acct.days_remaining == 4
    assert not acct.is_inactive
    assert acct.deadline == acct.last_trade_date + timedelta(days=14)
    acct.last_trade_date = timezone.now() - timedelta(days=14)
    assert acct.is_inactive


@pytest.mark.django_db
def test_fourteen_day_account_reminded_on_day_14_never_after(user, settings):
    settings.REMINDER_SEND_HOURS = [timezone.now().hour]
    ReminderSchedule.objects.create(days_left=[0])
    on_deadline = _acct(user, days_ago=14, inactivity_days=14, name="Day14")
    _acct(user, days_ago=15, inactivity_days=14, name="Day15")
    _acct(user, days_ago=14, name="Thirty")  # 16 left: not due

    with mock.patch.object(tasks, "send_mail"):
        summary = tasks.run_reminders()

    assert summary.sent == 1
    assert ReminderHistory.objects.get().account == on_deadline


@pytest.mark.django_db
def test_next_reminder_uses_limit(user, settings):
    settings.REMINDER_SEND_HOURS = [9]
    ReminderSchedule.objects.create(days_left=[0])
    acct = _acct(user, inactivity_days=14)
    nxt = timezone.localtime(acct.next_reminder_datetime(), user.get_timezone())
    today = timezone.localtime(timezone.now(), user.get_timezone()).date()
    assert (nxt.date() - today).days == 14 and nxt.hour == 9


# --- forms -----------------------------------------------------------------


def _form_data(**overrides):
    data = {
        "account_name": "A",
        "last_trade_date": timezone.now().strftime("%Y-%m-%dT%H:%M"),
        "inactivity_days": "30",
        "reminder_days_left": "",
        "notify_email": "on",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_account_form_override_parsed(user):
    form = TradingAccountForm(data=_form_data(reminder_days_left="1, 10,5"))
    assert form.is_valid(), form.errors
    assert form.cleaned_data["reminder_days_left"] == [10, 5, 1]


@pytest.mark.django_db
def test_account_form_blank_override_inherits(user):
    form = TradingAccountForm(data=_form_data())
    assert form.is_valid(), form.errors
    assert form.cleaned_data["reminder_days_left"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"reminder_days_left": "5, soon"}, "reminder_days_left"),
        ({"inactivity_days": "14", "reminder_days_left": "20, 3"}, "reminder_days_left"),
        ({"inactivity_days": "0"}, "inactivity_days"),
        ({"inactivity_days": "400"}, "inactivity_days"),
    ],
)
def test_account_form_rejects_bad_input(user, overrides, field):
    form = TradingAccountForm(data=_form_data(**overrides))
    assert not form.is_valid()
    assert field in form.errors


@pytest.mark.django_db
def test_account_form_shows_override_as_text(user):
    acct = _acct(user, reminder_days_left=[10, 3])
    form = TradingAccountForm(instance=acct)
    assert 'value="10, 3"' in str(form["reminder_days_left"])


@pytest.mark.django_db
def test_profile_form_saves_default_days_left(user):
    form = ProfileForm(
        data={"email": user.email, "first_name": "J", "last_name": "D", "reminder_days_left": "7 3 1"},
        instance=user,
    )
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.reminder_days_left == [7, 3, 1]


# --- set_reminder_days -----------------------------------------------------


@pytest.mark.django_db
def test_set_reminder_days_takes_days_left():
    call_command("set_reminder_days", "20", "10", "1", "0", stdout=StringIO())
    assert ReminderSchedule.get().days_left_list() == (20, 10, 1, 0)


@pytest.mark.django_db
def test_set_reminder_days_converts_days_after():
    call_command("set_reminder_days", "--days-after", "10", "15", "30", stdout=StringIO())
    assert ReminderSchedule.get().days_left_list() == (20, 15, 0)


@pytest.mark.django_db
def test_schedule_validator_rejects_empty_and_out_of_range():
    from django.core.exceptions import ValidationError

    for bad in ([], [-1], [400], ["x"]):
        with pytest.raises(ValidationError):
            ReminderSchedule(days_left=bad).full_clean()
