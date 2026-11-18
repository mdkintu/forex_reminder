"""Phase 5: urgency dashboard, calendar (.ics) feed, snooze, per-user send hours."""

import json
from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

import trades.tasks as tasks
from accounts.forms import ProfileForm
from trades.models import ReminderHistory, ReminderSchedule, TradingAccount


def _acct(user, days_ago, **kw):
    return TradingAccount.objects.create(
        user=user,
        account_name=kw.pop("name", "Acct"),
        last_trade_date=timezone.now() - timedelta(days=days_ago),
        notify_email=True,
        **kw,
    )


# --- urgency ---------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("days_ago,expected", [(28, "danger"), (25, "warning"), (10, "success"), (31, "secondary")])
def test_urgency_buckets(user, days_ago, expected):
    assert _acct(user, days_ago).urgency == expected


@pytest.mark.django_db
def test_dashboard_most_urgent_first_closed_last(authenticated_client, user):
    _acct(user, 10, name="Relaxed")
    _acct(user, 40, name="Closed")
    _acct(user, 28, name="Urgent")
    html = authenticated_client.get(reverse("accounts:dashboard")).content.decode()
    assert html.index("Urgent") < html.index("Relaxed") < html.index("Closed")
    assert "border-danger" in html


# --- calendar feed ---------------------------------------------------------


@pytest.mark.django_db
def test_calendar_feed(client, user, settings):
    settings.SITE_DOMAIN = "fair.example.com"
    active = _acct(user, 10, name="Live, Phase 2")
    _acct(user, 40, name="Gone")
    token = user.get_or_create_calendar_token()

    response = client.get(reverse("accounts:calendar_feed", args=[token]))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/calendar")
    body = response.content.decode()
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.rstrip().endswith("END:VCALENDAR")
    assert f"UID:fair-account-{active.pk}@fair.example.com" in body
    assert active.deadline.strftime("DTSTART:%Y%m%dT%H%M%SZ") in body.replace("\r\n ", "")
    assert "TRIGGER:-P3D" in body and "TRIGGER:-P1D" in body
    assert "Live\\, Phase 2" in body  # RFC 5545 escaping
    assert "Gone" not in body  # past-deadline accounts are left out
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))


@pytest.mark.django_db
def test_calendar_bad_token_404(client, user):
    assert client.get(reverse("accounts:calendar_feed", args=["nope"])).status_code == 404


@pytest.mark.django_db
def test_calendar_token_regenerate(authenticated_client, client, user):
    old = user.get_or_create_calendar_token()
    authenticated_client.post(reverse("accounts:profile"), {"regenerate_calendar": "1"})
    user.refresh_from_db()
    assert user.calendar_token and user.calendar_token != old
    assert client.get(reverse("accounts:calendar_feed", args=[old])).status_code == 404


@pytest.mark.django_db
def test_profile_shows_calendar_link(authenticated_client, user):
    html = authenticated_client.get(reverse("accounts:profile")).content.decode()
    user.refresh_from_db()
    assert user.calendar_token in html


# --- snooze ----------------------------------------------------------------


@pytest.fixture
def send_now(settings):
    settings.REMINDER_SEND_HOURS = [timezone.now().hour]


@pytest.mark.django_db
def test_snooze_suppresses_reminder(user, send_now):
    ReminderSchedule.objects.create(days_left=[20])
    acct = _acct(user, 10)
    acct.snooze(1)
    with mock.patch.object(tasks, "send_mail") as send:
        summary = tasks.run_reminders()
    assert summary.reasons[tasks.SNOOZED] == 1 and summary.sent == 0
    send.assert_not_called()


@pytest.mark.django_db
def test_snooze_never_blocks_final_day(user, send_now):
    ReminderSchedule.objects.create(days_left=[1])
    acct = _acct(user, 29)  # 1 day left
    acct.snooze(7)
    with mock.patch.object(tasks, "send_mail"):
        assert tasks.run_reminders().sent == 1


@pytest.mark.django_db
def test_mark_traded_clears_snooze(user):
    acct = _acct(user, 10)
    acct.snooze(3)
    acct.mark_traded()
    acct.refresh_from_db()
    assert acct.snoozed_until is None


@pytest.mark.django_db
def test_next_reminder_skips_snoozed_days(user, settings):
    settings.REMINDER_SEND_HOURS = [9]
    ReminderSchedule.objects.create(days_left=[20, 15])  # days 10 and 15
    acct = _acct(user, 0)
    acct.snooze(12)
    tz = user.get_timezone()
    nxt = timezone.localtime(acct.next_reminder_datetime(), tz)
    assert (nxt.date() - timezone.localtime(timezone.now(), tz).date()).days == 15


@pytest.mark.django_db
def test_snooze_view(authenticated_client, user, second_user, client):
    acct = _acct(user, 10)
    url = reverse("trades:snooze", args=[acct.pk])
    authenticated_client.post(url, {"days": "3"})
    acct.refresh_from_db()
    assert timedelta(days=2, hours=23) < acct.snoozed_until - timezone.now() <= timedelta(days=3)

    authenticated_client.post(url, {"days": "0"})  # cancel
    acct.refresh_from_db()
    assert acct.snoozed_until is None

    assert authenticated_client.post(url, {"days": "99"}).status_code == 400
    client.force_login(second_user)
    assert client.post(url, {"days": "1"}).status_code == 404


@pytest.mark.django_db
def test_telegram_snooze_button(client, user, settings):
    settings.TELEGRAM_WEBHOOK_SECRET = "s"
    acct = _acct(user, 10)
    update = {
        "update_id": 1,
        "callback_query": {
            "id": "q", "from": {"id": int(user.telegram_chat_id)}, "data": f"snooze:{acct.pk}:3",
            "message": {"message_id": 5, "chat": {"id": int(user.telegram_chat_id)}, "text": "reminder"},
        },
    }
    with mock.patch("accounts.telegram_bot.answer_callback_query"), \
         mock.patch("accounts.telegram_bot.edit_message_text") as edit:
        client.post(reverse("accounts:telegram_webhook"), data=json.dumps(update),
                    content_type="application/json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s")
    acct.refresh_from_db()
    assert acct.snoozed_until and acct.snoozed_until > timezone.now() + timedelta(days=2)
    assert "Snoozed" in edit.call_args.args[2]


@pytest.mark.django_db
def test_telegram_reminder_offers_snooze(user):
    acct = _acct(user, 10)
    with mock.patch.object(tasks, "send_telegram_message") as send:
        tasks._send_telegram(acct, 10)
    datas = [d for row in send.call_args.kwargs["buttons"] for _, d in row]
    assert f"snooze:{acct.pk}:1" in datas


# --- per-user send hours ---------------------------------------------------


@pytest.mark.django_db
def test_user_hours_override_setting(user, settings):
    settings.REMINDER_SEND_HOURS = [9, 14]
    user.reminder_hours = [20]
    user.save()
    acct = _acct(user, 10)
    at = lambda h: timezone.now().replace(hour=h, minute=0, second=0, microsecond=0)  # noqa: E731
    hours = user.get_reminder_hours()
    assert hours == [20]
    assert tasks.evaluate_account(acct, (10,), hours, 3, now=at(21)).due
    assert tasks.evaluate_account(acct, (10,), hours, 3, now=at(14)).reason == tasks.NO_SLOT_DUE


@pytest.mark.django_db
def test_run_uses_user_hours(user, settings):
    now_hour = timezone.now().hour
    settings.REMINDER_SEND_HOURS = [(now_hour + 12) % 24]  # site hours: not now
    user.reminder_hours = [now_hour]
    user.save()
    ReminderSchedule.objects.create(days_left=[20])
    _acct(user, 10)
    with mock.patch.object(tasks, "send_mail"):
        assert tasks.run_reminders().sent == 1
    assert ReminderHistory.objects.get().slot_hour == now_hour


@pytest.mark.django_db
def test_next_reminder_uses_user_hours(user, settings):
    settings.REMINDER_SEND_HOURS = [9]
    user.reminder_hours = [18]
    user.save()
    ReminderSchedule.objects.create(days_left=[20])
    acct = _acct(user, 0)
    assert timezone.localtime(acct.next_reminder_datetime(), user.get_timezone()).hour == 18


def _profile_data(user, **kw):
    data = {"email": user.email, "first_name": "J", "last_name": "D"}
    data.update(kw)
    return data


@pytest.mark.django_db
def test_profile_form_hours(user):
    form = ProfileForm(data=_profile_data(user, reminder_hours=["18", "8"]), instance=user)
    assert form.is_valid(), form.errors
    form.save()
    user.refresh_from_db()
    assert user.reminder_hours == [8, 18]

    form = ProfileForm(data=_profile_data(user), instance=user)  # none ticked = site default
    assert form.is_valid()
    form.save()
    user.refresh_from_db()
    assert user.reminder_hours is None and user.get_reminder_hours()


@pytest.mark.django_db
def test_profile_form_rejects_more_than_three_hours(user):
    form = ProfileForm(data=_profile_data(user, reminder_hours=["8", "12", "16", "20"]), instance=user)
    assert not form.is_valid() and "reminder_hours" in form.errors


def test_calendar_escaping():
    from accounts.calendar import _escape

    assert _escape("a;b,c\\d\ne") == r"a\;b\,c\\d\n" + "e"
