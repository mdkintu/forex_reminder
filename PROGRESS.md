# FAIR (Forex Account Inactivity Reminder) — System State Summary

**Last updated:** 2026-11-19 | **Git SHA:** `61ca270` (roadmap phases 1–5 done and deployed)

---

## Live status (2026-11-19)

- **Deployed** to `/home/tergfern/fair` at `61ca270`: all migrations applied on MariaDB (accounts 0006–0007, trades 0005–0009), `set_telegram_webhook` done (callbacks + command menu), app restarted.
- **Root cause of the Oct/Nov outage** (fixed in `2530a77`): dedup ignored the trade cycle, so each account got each reminder day once per lifetime; nothing was sent after 2026-10-06. Fixed with `ReminderHistory.cycle_start` (trades 0005).
- **Live schedule:** `20 15 10 5 3 2 1 0` days left (note: drops the default's "4 left"; restore with `python manage.py set_reminder_days 20 15 10 5 4 3 2 1 0` if wanted).
- **Cron:** hourly `send_reminders >> reminders.log` (unchanged). Dry run on 2026-11-18 showed accounts #4/#5 due a day-15 catch-up at 14:00 EAT.
- **Daily admin report:** `admin@fair.tergym.com` is the only superuser and has no Telegram connected, and the owner wants to keep it that way. So the report needs `ADMIN_TELEGRAM_CHAT_ID=<owner's existing chat id>` in the server `.env` (otherwise it falls back to emailing admin@fair.tergym.com). Check: `python manage.py shell -c "from trades.reporting import report_recipients; print(report_recipients())"`.

### Still to verify on the server
- [ ] `ADMIN_TELEGRAM_CHAT_ID` added to `.env` and the first daily report arrives (after 06:00 UTC / 09:00 EAT).
- [ ] `reminders.log` shows the catch-up sends for accounts #4/#5.
- [ ] Email delivery: history so far shows only Telegram rows; use **Send me a test reminder** on the profile page.
- [ ] Tidy: remove the duplicate `EMAIL_BACKEND` line in the server `.env`.
- [ ] Optional: `HEALTHCHECK_PING_URL` (e.g. healthchecks.io) to catch a dead cron.

### Prop-firm inactivity limits (for each account's "Inactivity days")
| Firm / account | Limit |
|---|---|
| FundedNext CFD (challenge + funded) | 30 days, not extendable (help centre; no 90-day rule found) |
| FundedNext Futures (challenge + funded) | 30 calendar days incl. weekends |
| The5ers evaluation / Bootcamp | 30 days |
| The5ers Pro (funded) | 60 days |
| The5ers Futures evaluation | 14 days |

Only a trade resets the count; logging in does not. Re-check firm rules periodically.

---

## Roadmap (plan approved 2026-11-18)

Five phases: 1 health monitoring, 2 one-tap "I traded" (email link + Telegram buttons/commands), 3 per-account inactivity limits + reminders as "days left", 4 reliable delivery (retries, catch-up, test reminder), 5 UX (urgency dashboard, .ics feed, snooze, per-user send hours). Deferred: MT4/MT5 auto-sync. WhatsApp stays hidden.

### Phase 1: health monitoring ✅ (deployed 2026-11-18)
- `send_reminders --dry-run`: per-account decision + reason, sends nothing.
- `trades.tasks.evaluate_account()` (pure decision) / `run_reminders()` (returns `RunSummary`); `check_and_send_reminders()` is a thin Celery wrapper.
- `ReminderRun` model logs every real run (read-only in admin).
- `trades/reporting.py`: daily admin report. Recipients (`report_recipients()`): `ADMIN_TELEGRAM_CHAT_ID` if set, else active superusers' connected Telegram chats, else `ADMIN_EMAILS`, else superusers' emails. It flags accounts ≤3 days from deadline with nothing delivered; `HEALTHCHECK_PING_URL` ping after each run.
- `LOGGING`: timestamped INFO logs for `trades`/`accounts` → `reminders.log`.
- **Deploy:** `git pull`, `migrate` (0006), optionally add `HEALTHCHECK_PING_URL` to `.env`, restart. (Set `ADMIN_TELEGRAM_CHAT_ID` when no superuser has Telegram connected, as on the live site.) Check: `python manage.py send_reminders --dry-run`.

### Phase 2: one-tap "I traded" ✅ (deployed 2026-11-18)
- `TradingAccount.mark_traded()`; dashboard + detail "I traded" button (`trades:mark_traded`, POST, owner only).
- Email reminders carry a signed 7-day link (`trades/tokens.py`, `trades:traded_link`): GET confirms, POST records.
- `accounts/telegram_bot.py`: `/status`, `/traded [name|#]`, `/help`, `/start <token>`, and `traded:<pk>` button callbacks (owner's chat only). Telegram reminders have an "✅ I traded" button.
- `trades/notifications.py`: shared `_run_bot` runner, `buttons=` on `send_telegram_message`, `answer_callback_query`, `edit_message_text`.
- **Deploy:** `git pull`, restart, then **re-run `python manage.py set_telegram_webhook`** (registers callbacks + command menu). Test: send `/status` to the bot.

### Phase 3: per-account limits, reminders as "days left" ✅ (deployed 2026-11-18)
- `TradingAccount.inactivity_days` (default 30) drives deadline, days left, past-deadline checks, report and bot.
- Reminder days are "days left" (0 = deadline day). `ReminderSchedule.day_list` → `days_left` (migration 0007 converts `30 - d`; live `[10,15,20]` → `[20,15,10]`). Default `[20,15,5,4,3,2,1,0]`.
- Overrides: `TradingAccount.reminder_days_left` > `User.reminder_days_left` > site schedule > default (`TradingAccount.reminder_days_left_values()` / `reminder_days()`).
- Forms: account form gets limit (14/21/30 presets) + optional days-left list; profile gets the user default. Helpers in `trades/daylists.py`.
- `set_reminder_days` takes days-left values (`--days-after` converts old style).
- **Deploy:** `git pull`, `migrate` (accounts 0006, trades 0007), restart. Then set the real schedule, e.g. `python manage.py set_reminder_days 20 15 10 5 3 2 1 0`, and set each account's limit if the firm isn't 30 days.

### Phase 4: reliable delivery ✅ (deployed 2026-11-18)
- `ReminderHistory.Status` (pending/sent/skipped/failed) + `attempts`, `error`, `catch_up` (migration 0008).
- Sends happen outside DB transactions; rows are claimed atomically (`trades.tasks._claim`); failures recorded and retried within the slot up to `REMINDER_MAX_ATTEMPTS` (3).
- Missed reminder days are caught up once within `REMINDER_CATCHUP_DAYS` (2); past-deadline is now checked first.
- Messages state days left before the account's own limit.
- Profile "Send me a test reminder" (`accounts:test_reminder`, 5-min cooldown) reports per-channel success/error. Account page shows status, tries, error.
- **Deploy:** `git pull`, `migrate` (trades 0008), restart. Then on the live site use **Send me a test reminder** to confirm SMTP works, and remove the duplicate `EMAIL_BACKEND` line from the server `.env`.

### Phase 5: UX polish ✅ (deployed 2026-11-18)
- Dashboard sorted by urgency (`TradingAccount.urgency`: danger ≤3, warning ≤7, success; past deadline last), shows limit and snooze state.
- `accounts/calendar.py`: private .ics feed (`accounts:calendar_feed`, `User.calendar_token`, regenerate on profile), alarms 3 days and 1 day before.
- Snooze: `TradingAccount.snoozed_until`, `snooze(days)`, `is_snoozed()` (never with ≤1 day left), `trades:snooze` view, Telegram `snooze:<pk>:<days>` button; `mark_traded` clears it. `evaluate_account` reason `snoozed`; `next_reminder_datetime` skips snoozed slots (rewritten as the `_upcoming_slots` generator).
- Per-user send hours: `User.reminder_hours` (≤3, profile checkboxes 06–22) via `User.get_reminder_hours()` in the task, next-reminder time and labels.
- **Deploy:** `git pull`, `migrate` (accounts 0007, trades 0009), restart.

### Deploy everything at once (phases 1–5)
`git pull && python manage.py migrate && touch tmp/restart.txt`, then: `python manage.py set_telegram_webhook`, `python manage.py set_reminder_days 20 15 10 5 3 2 1 0`, optionally add `HEALTHCHECK_PING_URL` to `.env`, restart, then `python manage.py send_reminders --dry-run` and "Send me a test reminder" on the profile page.

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
  - `inactivity_days`: per-account limit (default 30)
  - `days_remaining`: inactivity_days - days_since (capped at 0)
  - `next_reminder_datetime()`: when next reminder fires (user's local TZ)
  - `time_until_next_reminder`: timedelta to next reminder
  - `next_reminder_label`: human-friendly label (e.g. "Today at 2:00 PM")
  - `is_inactive`: past the account's limit
  - `deadline`: last_trade_date + inactivity_days
  - `reminder_days()`, `snoozed_until`/`snooze()`, `mark_traded()`, `urgency`

### ReminderSchedule (trades/models.py)
- Singleton JSON field `days_left` (days before each account's deadline; default [20,15,5,4,3,2,1,0]; 0 = deadline day)
- `ReminderSchedule.get()`: returns existing or unsaved default
- 0 (deadline day) is in the default: compared by calendar day (local TZ), not the exact deadline instant

### ReminderHistory (trades/models.py)
- FK to TradingAccount; fields: day_number, sent_at, channel (email/whatsapp/telegram), status (pending/sent/skipped/failed), attempts, error, catch_up, slot_hour, cycle_start
- `cycle_start` = the account's `last_trade_date` when sent (which inactivity cycle it belongs to); NULL for pre-0005 rows from past cycles
- Unique constraint: (account, cycle_start, day_number, channel, slot_hour) prevents dupes within a cycle; a new trade starts a fresh cycle

---

## Completed Features

1. **User auth** — email-only signup/login, email confirmation, password reset
2. **Custom user model** — no username, timezone field (auto-detected from browser)
3. **Trading account CRUD** — create, read, update, delete with user isolation
4. **Inactivity tracking** — `days_since_last_trade` computed in local TZ
5. **Reminder scheduling** — send hours per user (site default 9 AM & 2 PM local), configurable days-left list
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
```text
run_reminders(dry_run=False) -> RunSummary   (check_and_send_reminders() wraps it for Celery)
  for each account:
    evaluate_account() -> Decision(reason, day_number, slot_hour, catch_up)
      order: past_deadline -> reminder day (or catch-up of a missed day within
      REMINDER_CATCHUP_DAYS) -> snoozed (never with <=1 day left) -> due slot
      (user's reminder_hours, within grace) -> traded since slot
    if due: per channel, claim the ReminderHistory row atomically, send outside
      the transaction, record sent/skipped/failed (+ error); failed rows retried
      up to REMINDER_MAX_ATTEMPTS
  writes a ReminderRun row (not for dry runs)
send_reminders command then: maybe_send_daily_report(), ping_healthcheck()
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
- Test suite (191 passing)
- Roadmap phases 1–5 (monitoring, one-tap traded, per-account limits, reliable delivery, UX)

### Known Limitations (Not Next Features, Just Context)
- **WhatsApp:** Currently hidden in UI (Twilio wired but needs phone validation)
- **Celery/Redis:** Optional; cron works fine without it
- **Deadline-day reminder (0 days left):** days are compared by local calendar day, so it fires even if the exact deadline passed earlier that day
- **MT4/MT5 auto-sync:** deferred; last trade date is still entered manually (or via one-tap "I traded")

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

1. **Check git log:** `git log --oneline -5` (last work on 2026-11-19); then the "Still to verify on the server" list above
2. **Review feature request:** If expanding reminder rules or adding reset/payout, read "Next Feature" above
3. **Run tests:** `pytest -v` (ensure everything still passes)
4. **Start dev server:** `python manage.py runserver`
5. **List open issues:** Search GitHub issues or code comments

**For new Claude chat:** Copy this file's first half (Tech Stack + Core Models) to avoid re-reading code.
