# FAIR (Forex Account Inactivity Reminder) — System State Summary

**Last updated:** 2026-11-18 | **Git SHA:** 0ecf9fb

---

## 2026-11-18: Production stopped sending reminders (fixed in code, deploy pending)

- **Bug (fixed, `2530a77`):** dedup ignored the trade cycle, so each account got each reminder day only once in its lifetime. Production sent nothing after 2026-10-06. Fix: `ReminderHistory.cycle_start` + migration `trades/0005`.
- **Prod config:** the live `ReminderSchedule` is `[10, 15, 20]`, so nothing is sent on days 21-30.
- **Pending on server** (`/home/tergfern/fair`): `git pull`, `python manage.py migrate`, `python manage.py set_reminder_days` (e.g. 10 15 20 25 26 27 28 29 30), restart the app. Then check `reminders.log` for "Sent ... reminder" lines and run `python manage.py sendtestemail` (history shows only Telegram rows).
- Cron (hourly `send_reminders >> reminders.log`) and `.env` were verified fine.

---

## Roadmap (plan approved 2026-11-18)

Five phases: 1 health monitoring, 2 one-tap "I traded" (email link + Telegram buttons/commands), 3 per-account inactivity limits + reminders as "days left", 4 reliable delivery (retries, catch-up, test reminder), 5 UX (urgency dashboard, .ics feed, snooze, per-user send hours). Deferred: MT4/MT5 auto-sync. WhatsApp stays hidden.

### Phase 1: health monitoring ✅ (deploy pending)
- `send_reminders --dry-run`: per-account decision + reason, sends nothing.
- `trades.tasks.evaluate_account()` (pure decision) / `run_reminders()` (returns `RunSummary`); `check_and_send_reminders()` is a thin Celery wrapper.
- `ReminderRun` model logs every real run (read-only in admin).
- `trades/reporting.py`: daily admin report (Telegram `ADMIN_TELEGRAM_CHAT_ID`, fallback `ADMIN_EMAILS`) flagging accounts ≤3 days from deadline with nothing delivered; `HEALTHCHECK_PING_URL` ping after each run.
- `LOGGING`: timestamped INFO logs for `trades`/`accounts` → `reminders.log`.
- **Deploy:** `git pull`, `migrate` (0006), add `ADMIN_TELEGRAM_CHAT_ID=<your chat id>` (and optionally `HEALTHCHECK_PING_URL`) to `.env`, restart. Check: `python manage.py send_reminders --dry-run`.

### Phase 2: one-tap "I traded" ✅ (deploy pending)
- `TradingAccount.mark_traded()`; dashboard + detail "I traded" button (`trades:mark_traded`, POST, owner only).
- Email reminders carry a signed 7-day link (`trades/tokens.py`, `trades:traded_link`): GET confirms, POST records.
- `accounts/telegram_bot.py`: `/status`, `/traded [name|#]`, `/help`, `/start <token>`, and `traded:<pk>` button callbacks (owner's chat only). Telegram reminders have an "✅ I traded" button.
- `trades/notifications.py`: shared `_run_bot` runner, `buttons=` on `send_telegram_message`, `answer_callback_query`, `edit_message_text`.
- **Deploy:** `git pull`, restart, then **re-run `python manage.py set_telegram_webhook`** (registers callbacks + command menu). Test: send `/status` to the bot.

---

## Tech Stack

- **Framework:** Django 5.2 LTS (Python 3.10+)
- **Database:** SQLite (dev), MySQL/MariaDB (prod via PyMySQL)
- **Auth:** django-allauth (email-only, custom User model, no username)
- **Notifications:** Twilio (WhatsApp), python-telegram-bot (Telegram), Django email
- **Background jobs:** Celery + django-celery-beat (optional, Redis broker)
- **Frontend:** Bootstrap 5, vanilla JS (timezone auto-detect, live countdown timers)
- **Testing:** pytest + pytest-django + pytest-cov
- **Deployment:** cPanel (shared hosting support), Passenger WSGI

**Key config:** Settable via `.env` (python-decouple):
- `REMINDER_SEND_HOURS`: Local hours for daily reminders (default: 9,14)
- `REMINDER_GRACE_HOURS`: Grace window for missed slots (default: 3)
- `SITE_DOMAIN`, `SITE_SCHEME` (HTTPS required for Telegram webhook)

---

## Core Data Models

### User (accounts/models.py)
- Custom `AbstractUser` (email is USERNAME_FIELD, no username field)
- Phone number, Telegram chat ID, timezone (auto-detected)
- Telegram link token + expiry (30-min validity for one-tap "Connect Telegram" flow)
- `get_timezone()`, `set_timezone_from_js()`, `get_or_create_telegram_link_token()`

### TradingAccount (trades/models.py)
- Fields: account_name, account_number, broker, last_trade_date
- Notification flags: notify_email (default True), notify_whatsapp, notify_telegram
- **Properties:**
  - `days_since_last_trade`: computed in user's local TZ
  - `days_remaining`: 30 - days_since (capped at 0)
  - `next_reminder_datetime()`: when next reminder fires (user's local TZ)
  - `time_until_next_reminder`: timedelta to next reminder
  - `next_reminder_label`: human-friendly label (e.g. "Today at 2:00 PM")
  - `is_inactive`: bool (days_since >= 30)
  - `deadline`: last_trade_date + 30 days

### ReminderSchedule (trades/models.py)
- Singleton JSON field `day_list` (reminder day numbers, default: [10,15,25,26,27,28,29,30])
- `ReminderSchedule.get()`: returns existing or unsaved default
- Day 30 is in the default: compared by calendar day (local TZ), not the exact deadline instant

### ReminderHistory (trades/models.py)
- FK to TradingAccount; fields: day_number, sent_at, channel (email/whatsapp/telegram), status (pending/sent/skipped), slot_hour, cycle_start
- `cycle_start` = the account's `last_trade_date` when sent (which inactivity cycle it belongs to); NULL for pre-0005 rows from past cycles
- Unique constraint: (account, cycle_start, day_number, channel, slot_hour) prevents dupes within a cycle; a new trade starts a fresh cycle

---

## Completed Features

1. **User auth** — email-only signup/login, email confirmation, password reset
2. **Custom user model** — no username, timezone field (auto-detected from browser)
3. **Trading account CRUD** — create, read, update, delete with user isolation
4. **Inactivity tracking** — `days_since_last_trade` computed in local TZ
5. **Reminder scheduling** — twice-daily slots (9 AM & 2 PM local), configurable day list
6. **Smart deduplication** — unique constraint on (account, cycle_start, day, channel, slot_hour)
7. **Multi-channel delivery** — email (Django), WhatsApp (Twilio), Telegram (bot)
8. **Telegram webhook** — one-tap "Connect Telegram" via `t.me/<bot>?start=<token>`
9. **Live countdowns** — JS ticking timers for inactivity deadline and next reminder
10. **Skip logic** — skip later-in-day slots if user traded after earlier slot that day
11. **Reminder history** — logs every reminder sent with channel & status
12. **Prop-firm UI** — landing page explains 30-day closure rule, CTA to sign up
13. **Light/dark theme** — auto-detected from OS, manual toggle in UI
14. **Production hardening** — HTTPS redirect, secure cookies, HSTS, security headers, static file serving
15. **Admin interface** — full Django admin for users, accounts, reminders, schedule
16. **Timezone auto-detect** — browser's `Intl.DateTimeFormat` on first dashboard visit
17. **Cron scheduling** — hourly `manage.py send_reminders` command (no Redis needed)
18. **Email confirmation** — profile email change sends verification link
19. **Legal pages** — privacy, terms, contact
20. **Tests** — pytest suite covering auth, CRUD, reminder logic, deduplication

---

## Current Working Code Summary

**Key logic in `trades/tasks.py`:**
```python
check_and_send_reminders():
  - Loop all TradingAccount.objects
  - Get days_since_last_trade (local TZ)
  - Skip if not in ReminderSchedule.days()
  - Skip if days_since > 30 (past deadline)
  - Get due_slot_hour (latest hour <= now, within grace_hours)
  - Skip if user traded after previous slot (later-in-day rule)
  - For each enabled channel (email/whatsapp/telegram):
    - Check ReminderHistory for existing (account, cycle_start=last_trade_date, day, channel, slot_hour)
    - If missing, create ReminderHistory(status=pending), send via SENDERS[channel]()
    - On success: status=sent, log info, increment sent_count
    - On no-credentials: status=skipped, log warning (don't retry)
    - On exception: log and continue
  - Return sent_count
```

**UI flow:**
- Public home.html: landing page + signup/login links
- Dashboard (login required): shows all user's accounts with live countdown timers (JS)
- Account detail: shows reminder history table, "last trade" field, inactivity countdown
- Account form: create/edit name, number, broker, notification channel toggles
- Profile page: email + password, "Connect Telegram" button (one-tap webhook)

**Deployment:**
- Cron entry: `0 * * * * cd /path && python manage.py send_reminders`
- Or Celery Beat (optional): `create_reminder_schedule` management command
- Static files: served via Django StaticFilesHandler on Passenger
- Email backend: console (dev) or SMTP (prod)

---

## Feature Status: Completed ✅ vs. Next

### Completed ✅
- All core reminder logic (scheduling, dedup, multi-channel)
- User auth, timezone handling, account management
- Telegram webhook integration (one-tap connect)
- Email confirmation (new email)
- Light/dark theme
- Legal pages (terms, privacy, contact)
- Production security (HTTPS, cookies, HSTS, headers)
- Admin interface
- Test suite (88 passing)

### Known Limitations (Not Next Features, Just Context)
- **WhatsApp:** Currently hidden in UI (Twilio wired but needs phone validation)
- **Celery/Redis:** Optional; cron works fine without it
- **Day-30 reminder:** Sent by default; days are compared by local calendar day, so it fires even if the exact deadline passed earlier that day

### **Next Feature to Build: Account Reset / Payout Flow**
The app currently monitors inactivity but lacks a "reset" workflow. After a user successfully completes a trading cycle (e.g., 30-day profit target), they should:

1. **Click "Request Reset"** on account detail page
2. **Broker confirms trade history** and verifies profitability/rule compliance
3. **System issues payout** (via external payment API or manual broker step)
4. **Resets `last_trade_date` to now** → inactivity counter restarts from 0

**New models needed:**
- `ResetRequest`: account FK, status (pending/approved/rejected/paid), request_date, broker_notes
- `Payout`: account FK, amount, method (bank_transfer/crypto/wallet), status

**New views:**
- ResetRequestCreateView (form: account selection, acknowledge terms)
- ResetRequestListView (admin: see pending resets, approve/reject/mark-paid)
- Broker integration endpoints (webhook to receive trade verification from prop firm)

**Why next:** Traders expect a complete cycle (monitor → trade → reset → repeat). Without this, the app is monitoring-only, not a full trading platform lifecycle tool.

---

## Key Files (Priority Order)

| File | Purpose | Status |
|------|---------|--------|
| `trades/models.py` | TradingAccount, ReminderHistory, ReminderSchedule | ✅ Complete |
| `trades/tasks.py` | `check_and_send_reminders()` core logic | ✅ Complete |
| `accounts/models.py` | Custom User, timezone, Telegram token | ✅ Complete |
| `templates/dashboard.html` | Account list with live countdown (JS tickers) | ✅ Complete |
| `templates/tradingaccount_detail.html` | Account detail + reminder history + edit | ✅ Complete |
| `accounts/views.py` | Auth, profile, Telegram webhook | ✅ Complete |
| `trades/views.py` | Account CRUD, reminder history view | ✅ Complete |
| `forex_reminder/settings.py` | Django config, security, Celery | ✅ Complete |
| `conftest.py` + test files | pytest fixtures, auth/CRUD/task tests | ✅ Complete |

---

## Quick Commands (Dev)

```bash
# Activate venv
source venv/bin/activate

# Run tests
pytest -v

# Dev server
python manage.py runserver

# Send reminders manually (test)
python manage.py send_reminders

# Create superuser
python manage.py createsuperuser

# Set reminder days
python manage.py set_reminder_days

# Telegram webhook setup (prod only)
python manage.py set_telegram_webhook
```

---

## Deployment Checklist (For Next Session)

- [ ] Set `SECRET_KEY` (prod, 50+ random chars)
- [ ] Set `DEBUG=False`
- [ ] Set `ALLOWED_HOSTS` (prod domain)
- [ ] Set `SITE_DOMAIN`, `SITE_SCHEME=https`
- [ ] Configure SMTP (EMAIL_HOST, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_PORT=587)
- [ ] Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`
- [ ] Run `python manage.py migrate` on prod DB
- [ ] Add cron: `0 * * * * cd /path && venv/bin/python manage.py send_reminders`
- [ ] Run `python manage.py set_telegram_webhook` (HTTPS only)
- [ ] Test email/Telegram delivery end-to-end

---

## Architecture Notes

- **Timezone correctness:** All inactivity counting done in user's local TZ (not UTC). This is crucial for global users.
- **Deduplication:** Unique constraint + IntegrityError catch prevents double-sends even with concurrent cron workers. Scoped per cycle (`cycle_start`) so reminders restart after each new trade.
- **Grace window:** Late cron runs (up to 3 hours) still deliver reminders, avoiding missed notifications.
- **Later-in-day skip rule:** If user trades after the 9 AM slot, the 2 PM slot is skipped same day.
- **Webhook security:** Telegram webhook signed with `TELEGRAM_WEBHOOK_SECRET`.

---

## Next-Session Entry Point

1. **Check git log:** `git log --oneline -5` (last work on 2026-11-18)
2. **Review feature request:** If expanding reminder rules or adding reset/payout, read "Next Feature" above
3. **Run tests:** `pytest -v` (ensure everything still passes)
4. **Start dev server:** `python manage.py runserver`
5. **List open issues:** Search GitHub issues or code comments

**For new Claude chat:** Copy this file's first half (Tech Stack + Core Models) to avoid re-reading code.
