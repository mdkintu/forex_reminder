# Forex Account Inactivity Reminder (FAIR)

**FAIR** (Forex Account Inactivity Reminder) is a Django application built for
**prop-firm and funded traders**. Most prop firms close accounts that go
30 days without a trade (some are stricter at 14 or 21 days). FAIR monitors
your trading accounts and reminds you via email, WhatsApp, and/or Telegram
when you've been inactive too long — so you never lose a funded account to an
inactivity clause.

It tracks the days since your last trade on each account and sends reminders
**twice daily (9 AM and 2 PM, in the user's local timezone)** on a configurable
schedule of day numbers (default: 10, 15, 25–29).

Built with:

- **Django 5.2 LTS** + custom email-only user model
- **django-allauth** for authentication (email + password, no username)
- **Celery + Redis** optional background task (see "Scheduling reminders")
- **Twilio** for WhatsApp reminders
- **python-telegram-bot** for Telegram reminders
- **Bootstrap 5** front-end templates

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running the app](#running-the-app)
- [Scheduling reminders](#scheduling-reminders)
- [Environment variables](#environment-variables)
- [The reminder task](#the-reminder-task)
- [Tests](#tests)
- [Admin](#admin)

---

## Features

- Users sign in with **email + password** only (no username).
- Each user's **timezone is auto-detected** from the browser on their first
  dashboard visit. Changing the email on the profile page sends a
  **confirmation link** to the new address.
- Users can manage any number of **trading accounts** (create, view, edit, delete),
  including an **account number** for each.
- Each account shows a **live inactivity countdown** to the 30-day deadline and a
  **live countdown to the next reminder**, both in the user's local timezone.
- Reminders send **twice per day** (9 AM & 2 PM local) on configured days after
  the last trade, via whichever channel(s) the user enabled (email, WhatsApp, Telegram).
- **Reminder history**: each account page logs when every reminder was sent and
  via which channel.
- Prop-firm awareness built in — the UI explains that firms close accounts
  inactive for ~30 days and that a single trade resets the inactivity counter.
- Duplicate reminders are avoided: each account+day+channel+slot is recorded
  in `ReminderHistory` exactly once.
- A custom Django admin for users, trading accounts, reminder history, and the
  global reminder schedule.

---

## Requirements

- Python 3.10+
- Redis **only** if you run the optional Celery scheduler (see below)
- A virtual environment manager (venv)

---

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url> forex_reminder
cd forex_reminder
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# or on Windows:
# venv\Scripts\activate
```

### 3. Install the dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

Copy the example env file and edit it to match your environment:

```bash
cp .env.example .env
```

At minimum you need a `SECRET_KEY` for production. For local development the
defaults (console email backend, SQLite, etc.) work out of the box. See
[Environment variables](#environment-variables) below for the full list.

### 5. Run database migrations

```bash
python manage.py migrate
```

### 6. Create a superuser (for the admin)

```bash
python manage.py createsuperuser
```

Enter your email address and password.

---

## Running the app

### Django development server

```bash
python manage.py runserver
```

Open <http://127.0.0.1:8000/> in your browser. The public landing page loads
without authentication; the dashboard, trading accounts, and profile pages
require login.

### Admin interface

Visit <http://127.0.0.1:8000/admin/> and sign in with the superuser you
created.

---

## Scheduling reminders

Reminders are triggered by running the `send_reminders` management command,
which calls `check_and_send_reminders`. How it runs depends on your host:

### Option A — cPanel / shared hosting cron (recommended, no Redis needed)

Add a `send_reminders` cron entry that runs often enough to catch both daily
slots (9 AM and 2 PM local). Because the task is cheap and internally gates on
the user's local hour, running it **hourly** is perfectly fine:

```
0 * * * *  cd /path/to/project && /path/to/venv/bin/python manage.py send_reminders
```

(The task sends each slot — e.g. 9 and 14 local — on the first run at or after
that hour, within `REMINDER_GRACE_HOURS`, and deduplicates per slot, so an
hourly cron catches both windows without double-sending.)

### Option B — Celery Beat (optional, needs Redis)

For a non-cPanel deployment you can instead use Celery with `django-celery-beat`:

```bash
redis-server
celery -A forex_reminder worker -l info
celery -A forex_reminder beat -l info
```

Then create the periodic schedule:

```bash
python manage.py create_reminder_schedule
```

> **Note:** `create_reminder_schedule` is **deprecated** and only useful if you
> adopt Celery Beat. Do **not** run it alongside the cron on the same host, or
> reminders would fire from both schedulers. If you do enable Beat later, update
> that command's 09:00 UTC schedule to match `REMINDER_SEND_HOURS` and the local
> timezone.

### Configuring reminder days

The default reminder day numbers are `[10, 15, 25, 26, 27, 28, 29]`. (No day-30
reminder by default: the deadline is exactly 30 days after the last trade, so a
day-30 reminder could arrive after the account is already closed. Reminders are
never sent once the deadline has passed.) To
change them interactively:

```bash
python manage.py set_reminder_days
```

---

## Environment variables

Config values are read from `.env` via `python-decouple`. All variables have
sensible development defaults, so you only need to set what you actually use.

| Variable                 | Default                         | Description |
| ------------------------ | ------------------------------- | ----------- |
| `SECRET_KEY`             | dev-only placeholder            | Django secret key (set a real one in production) |
| `DEBUG`                  | `True`                          | Django debug mode |
| `ALLOWED_HOSTS`          | `localhost,127.0.0.1`           | Comma-separated allowed hosts |
| `SITE_NAME`              | `FAIR`                          | Shown in confirmation/verification emails and SEO tags |
| `SITE_DOMAIN`            | `127.0.0.1:8000`                | Your real domain in production, e.g. `fair.tergym.com` |
| `SITE_SCHEME`            | `http` (`https` when `DEBUG=False`) | Must be `https` in production — required for the Telegram webhook |
| `DB_NAME`                | `db.sqlite3`                    | SQLite database file |
| `TIME_ZONE`              | `UTC`                           | Application time zone |
| `REDIS_URL`              | `redis://localhost:6379/0`      | Celery broker/result backend |
| `EMAIL_BACKEND`          | `console` backend               | Email backend (use SMTP in production) |
| `DEFAULT_FROM_EMAIL`     | `webmaster@localhost`           | Sender address for reminder emails |
| `EMAIL_HOST`             | `localhost`                     | SMTP host |
| `EMAIL_PORT`             | `587`                           | SMTP port |
| `EMAIL_HOST_USER`        | *(empty)*                       | SMTP username |
| `EMAIL_HOST_PASSWORD`    | *(empty)*                       | SMTP password |
| `EMAIL_USE_TLS`          | `True` (unless SSL is on)       | STARTTLS for SMTP (port 587) |
| `EMAIL_USE_SSL`          | `False`                         | Implicit SSL for SMTP (port 465); turns TLS off |
| `EMAIL_TIMEOUT`          | `30`                            | SMTP timeout in seconds |
| `REMINDER_SEND_HOURS`    | `9,14`                          | Comma-separated local hours (0-23) for the daily reminder slots |
| `REMINDER_GRACE_HOURS`   | `3`                             | A missed slot is still sent on a cron run up to this many hours late |
| `TWILIO_ACCOUNT_SID`     | *(empty)*                       | Twilio account SID (WhatsApp) |
| `TWILIO_AUTH_TOKEN`      | *(empty)*                       | Twilio auth token |
| `TWILIO_PHONE_NUMBER`    | *(empty)*                       | Twilio phone number |
| `TWILIO_WHATSAPP_FROM`   | *(empty)*                       | Twilio WhatsApp-enabled sender (E.164) |
| `TELEGRAM_BOT_TOKEN`     | *(empty)*                       | Telegram bot token |
| `TELEGRAM_BOT_USERNAME`  | *(empty)*                       | Bot's public @username (no `@`) — powers the "Connect Telegram" deep link |
| `TELEGRAM_WEBHOOK_SECRET`| *(empty)*                       | Random secret verifying incoming Telegram webhook calls |

> ⚠️ **`DEBUG`** defaults to `True` for local convenience, but you **must set
> `DEBUG=False` explicitly in production** (e.g. in your `.env`). Shipping with
> `DEBUG=True` is a security risk.

If the Twilio or Telegram credentials are missing, the corresponding
notification functions simply log a warning and skip sending — development
never crashes.

### Connecting Telegram

Telegram bots can't message a user who has never contacted them first — that's
a platform-level anti-spam rule, not something this app controls. To make that
as close to frictionless as possible, the profile page offers a one-tap
"Connect Telegram" button instead of asking users to find and type a numeric
chat ID:

1. The user taps **Connect Telegram**, which opens
   `t.me/<TELEGRAM_BOT_USERNAME>?start=<token>` in Telegram with a
   per-user, 30-minute token.
2. They tap Telegram's own **Start** button — that's the one unavoidable
   message-to-the-bot Telegram requires.
3. Telegram calls this app's webhook (`accounts.views.telegram_webhook`) with
   that `/start <token>` message; the webhook resolves the token back to the
   user, saves the resulting chat id, and replies with a confirmation.

This needs a one-time setup step in production (HTTPS only — Telegram refuses
plain HTTP webhooks):

```bash
# TELEGRAM_WEBHOOK_SECRET must be set in .env first, and SITE_SCHEME=https.
python manage.py set_telegram_webhook          # register it
python manage.py set_telegram_webhook --info   # check what's currently registered
python manage.py set_telegram_webhook --delete # unregister it
```

Re-run `set_telegram_webhook` any time `SITE_DOMAIN`, `TELEGRAM_BOT_TOKEN`, or
`TELEGRAM_WEBHOOK_SECRET` change.

---

## The reminder task

The core task is `check_and_send_reminders` in `trades/tasks.py`. It:

1. Reads the global `ReminderSchedule` to get the list of reminder day numbers.
2. Loops over every trading account; for each, computes the days since the
   last trade (in the account owner's local timezone).
3. Only acts when a slot in `REMINDER_SEND_HOURS` (default 9 AM and 2 PM
   local) is due: the latest slot at or before the owner's local hour, up to
   `REMINDER_GRACE_HOURS` late (so a delayed cron run still delivers it).
   Accounts already past their 30-day deadline are skipped.
4. On a scheduled day, sends a reminder on every channel the user has enabled
   (email, WhatsApp, Telegram), recording each as `pending` first. A channel
   with no credentials or no recipient (phone / chat id) is recorded as
   `skipped`, not `sent`.
5. Skips the later-in-day slot (e.g. the 2 PM one) if the user placed a trade
   **after** the earlier slot that day (they already reacted to the 9 AM one).
6. Writes a `ReminderHistory` row for each account+day+channel+slot before
   sending, and marks it `sent` afterward. The database's unique constraint
   guarantees a reminder is never sent twice for the same slot.

The next reminder time (for the live countdown on the UI) is computed by
`TradingAccount.next_reminder_datetime()`, which mirrors these same rules.

---

## Tests

The project uses **pytest** and **pytest-django**, covering:

- User registration and login (email-only, via allauth).
- Redirecting anonymous users away from protected pages.
- Trading account CRUD for logged-in users (create, read, update, delete),
  including object-isolation (you can't touch another user's accounts).
- The `days_remaining` property (deadline = `last_trade_date` + 30 days).
- The `check_and_send_reminders` task: notification functions are mocked,
  accounts with different `last_trade_date`s are checked, correct
  `ReminderHistory` entries are asserted, and duplicate reminders are avoided.
- The public landing page loads.
- Django admin registrations.

### Run the tests

```bash
pytest
```

For verbose output:

```bash
pytest -v
```

---

## Admin

The Django admin includes all three core models:

- **Users** — search by email/name/phone, filter by staff/active/superuser.
- **Trading accounts** — search by name/broker/user, filter by notification
  preferences and owner, with an inline view of that account's reminder history.
- **Reminder history** — search by account, filter by channel/status.
- **Reminder schedule** — the global list of reminder day numbers.

---

## Project layout

```
forex_reminder/
├── accounts/          # Custom User model, allauth integration, landing/profile pages
├── trades/            # TradingAccount, ReminderSchedule, ReminderHistory, reminder task
├── forex_reminder/    # Django project config (settings, urls, celery)
├── templates/         # Bootstrap 5 templates
├── static/            # CSS/JS/images
├── manage.py
└── requirements.txt
```
