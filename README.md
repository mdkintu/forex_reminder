# Forex Account Inactivity Reminder (FAIR)

**FAIR** (Forex Account Inactivity Reminder) is a Django application that
monitors your forex trading accounts and reminds you via email, WhatsApp,
and/or Telegram when you've been inactive too long. It tracks the days since
your last trade on each account and sends reminders on a configurable schedule
of day numbers (default: 10, 15, 25–30).

Built with:

- **Django 5.0** + custom email-only user model
- **django-allauth** for authentication (email + password, no username)
- **Celery + Redis** for the background reminder task (with django-celery-beat)
- **Twilio** for WhatsApp reminders
- **python-telegram-bot** for Telegram reminders
- **Bootstrap 5** front-end templates

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running the app](#running-the-app)
- [Running Celery](#running-celery)
- [Environment variables](#environment-variables)
- [The reminder task](#the-reminder-task)
- [Tests](#tests)
- [Admin](#admin)

---

## Features

- Users sign in with **email + password** only (no username).
- Users can manage any number of **trading accounts** (create, view, edit, delete).
- Each account tracks `last_trade_date`; the app shows a live countdown to the
  30-day inactivity deadline.
- A scheduled **Celery task** sends reminders on configurable days after the
  last trade via the channels the user has enabled.
- Duplicate reminders are avoided: each account+day+channel combo is recorded
  in `ReminderHistory` exactly once.
- A custom Django admin for users, trading accounts, reminder history, and the
  global reminder schedule.

---

## Requirements

- Python 3.10+
- Redis (for the Celery broker/backend)
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

## Running Celery

The reminder task runs in the background via Celery. You need Redis running
first, then start a worker and the beat (scheduler) process.

### 1. Start Redis

```bash
redis-server
```

> If you use Docker: `docker run -p 6379:6379 redis`

### 2. Start a Celery worker

From the project directory (with the venv activated):

```bash
celery -A forex_reminder worker -l info
```

### 3. Start the Celery beat scheduler

Beat periodically triggers the `check_and_send_reminders` task. In development
you can start it from the Django admin under **Periodic tasks**, or run:

```bash
celery -A forex_reminder beat -l info
```

#### Creating a periodic schedule (optional)

You can create the schedule programmatically:

```bash
python manage.py create_reminder_schedule
```

The default reminder day numbers are `[10, 15, 25, 26, 27, 28, 29, 30]`. To
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
| `DB_NAME`                | `db.sqlite3`                    | SQLite database file |
| `TIME_ZONE`              | `UTC`                           | Application time zone |
| `REDIS_URL`              | `redis://localhost:6379/0`      | Celery broker/result backend |
| `EMAIL_BACKEND`          | `console` backend               | Email backend (use SMTP in production) |
| `DEFAULT_FROM_EMAIL`     | `webmaster@localhost`           | Sender address for reminder emails |
| `EMAIL_HOST`             | `localhost`                     | SMTP host |
| `EMAIL_PORT`             | `587`                           | SMTP port |
| `EMAIL_HOST_USER`        | *(empty)*                       | SMTP username |
| `EMAIL_HOST_PASSWORD`    | *(empty)*                       | SMTP password |
| `EMAIL_USE_TLS`          | `True`                          | Use TLS for SMTP |
| `TWILIO_ACCOUNT_SID`     | *(empty)*                       | Twilio account SID (WhatsApp) |
| `TWILIO_AUTH_TOKEN`      | *(empty)*                       | Twilio auth token |
| `TWILIO_PHONE_NUMBER`    | *(empty)*                       | Twilio phone number |
| `TWILIO_WHATSAPP_FROM`   | *(empty)*                       | Twilio WhatsApp-enabled sender (E.164) |
| `TELEGRAM_BOT_TOKEN`     | *(empty)*                       | Telegram bot token |

If the Twilio or Telegram credentials are missing, the corresponding
notification functions simply log a warning and skip sending — development
never crashes.

---

## The reminder task

The core task is `check_and_send_reminders` in `trades/tasks.py`. It:

1. Reads the global `ReminderSchedule` to get the list of reminder day numbers.
2. Loops over every trading account; for each, computes the days since the
   last trade.
3. If that day number is in the schedule, sends a reminder on every channel the
   user has enabled (email, WhatsApp, Telegram).
4. Writes a `ReminderHistory` row for each account+day+channel before sending,
   and marks it `sent` afterward. The database's unique constraint guarantees
   a reminder is never sent twice for the same account+day+channel.

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
