# FAIR (Forex Account Inactivity Reminder) — System State Summary

**Last updated:** 2026-11-26 | **Git SHA:** `826f1e1` (server still at `5481f94`: the timezone fix is pushed to `main` but not yet pulled on the server)

---

## Next steps (updated 2026-11-26)

0. **Deploy the timezone fix (`826f1e1`):** `git pull`, `migrate` (nothing to apply) and restart (see "Website shows the user's own timezone"). Then the GFT account page should show its last trade as Nov 19, 2026 17:30.
1. **Sync the other four accounts:** "$50k Phase 2" (#5), "$5k Live Account" (#7) and the two "$5k Phase 1" (#6, #8). For each, find the firm (ask the owner, or look it up through the FundedNext connector) and the computer it's traded from. Set its *Account number* on FAIR to its MT5 login, then:
   - **FundedNext CFD, $50k and up:** send the question below and keep using "I traded" until FundedNext says yes in writing.
   - **FundedNext under $50k, or The5ers:** a separate MT5 with the investor password, or the trading MT5 if an EA the firm allows already trades there (FAIR Sync on a chart with no other EA).
2. **Reset/payout feature:** design it first (see "Next Feature to Build").

Already done: GFT "$10K Phase 2" syncs since 2026-11-24 (see "MT5 auto-sync"). Its Goat Funded Trader question (drafted 2026-11-23) is optional now. If it's sent, reword it first: FAIR Sync runs in the trading terminal next to the owner's own bot, not in a separate investor terminal.

**FundedNext question** (drafted 2026-11-23, not sent). Fill in the brackets and check that every statement is true for that account before sending:

> Hi,
>
> Before I use something on my FundedNext CFD account [login] ($[size]), I'd like your confirmation in writing.
>
> I wrote a small Expert Advisor for my own use that reminds me before the account reaches the 30-day inactivity limit. It:
> - runs in a separate MT5 terminal logged in with the account's **investor (read-only) password**, on my own computer and home internet connection, the same ones I trade from (no VPS or VPN);
> - only reads the account's trade history (the time of my latest opened trade) and sends it to my personal reminder app;
> - never opens, changes or closes orders. It can't, because the investor login has no trading rights, and Algo Trading stays off in that terminal.
>
> I place all my trades manually from my usual terminal or phone.
>
> As accounts of $50k and above can't use EAs or automated tools, is this read-only setup allowed on my account? If it isn't, I'll keep tracking inactivity manually.
>
> Thank you.

---

## Live status (2026-11-24)

- **Deployed** to `/home/tergfern/fair` at `46b41af` on 2026-11-23: MT5 auto-sync + the Telegram date & time picker. All migrations applied on MariaDB (accounts 0006–0008, trades 0005–0010), `set_telegram_webhook` done (callbacks + command menu), app restarted. Check after it: the sync endpoint returns 401 for a fake key, home and login pages 200.
- **Server python:** run `manage.py` as `/home/tergfern/virtualenv/fair/3.12/bin/python` (the one the cron uses), never bare `python`. The SSH shell can start inside another app's virtualenv (phamily-sacco, prompt `(backend:3.11)`), where `migrate` fails with `No module named 'celery'`. Run `migrate` and see it succeed **before** `touch tmp/restart.txt`.
- **2026-11-23 deploy incident:** `migrate` ran in that wrong virtualenv and failed, but the app was restarted anyway, so the new code ran without the new columns: the sync endpoint returned 500 (logged-in pages most likely too) and all eight hourly runs from 13:00 to 20:00 UTC crashed (`Unknown column 'trades_tradingaccount.mt5_last_seen'`). Fixed by 20:18 UTC by migrating with FAIR's python. No reminders were lost: the dry run afterwards showed no account due and no catch-up pending (next reminders 28–30 Nov).
- **Root cause of the Oct/Nov outage** (fixed in `2530a77`): dedup ignored the trade cycle, so each account got each reminder day once per lifetime; nothing was sent after 2026-10-06. Fixed with `ReminderHistory.cycle_start` (trades 0005).
- **Live schedule:** `20 15 10 5 3 2 1 0` days left (note: drops the default's "4 left"; restore with `python manage.py set_reminder_days 20 15 10 5 4 3 2 1 0` if wanted).
- **Monitoring:** two healthchecks.io checks, both alerting on Telegram through @HealthchecksBot. "FAIR reminders" is pinged by the hourly job (`HEALTHCHECK_PING_URL`). "FAIR website" is pinged by a 5-minute server cron that loads `/health/` (see "Website health check"). Keep the ping URLs out of git.
- **Cron:** hourly `cd /home/tergfern/fair && /home/tergfern/virtualenv/fair/3.12/bin/python manage.py send_reminders >> reminders.log 2>&1`, plus the 5-minute website check. The crontab is shared with ngw and Phamily SACCO and runs on Kampala time (`CRON_TZ=Africa/Kampala`). To change it, back it up, edit a copy, check the copy, then install it with `crontab <file>`. Never pipe into `crontab -`: on 2026-11-24 a failed `crontab -l | sed … | crontab -` installed an empty crontab and wiped every job for a few minutes (restored from `~/crontab.backup` by 21:29 EAT). Dry run on 2026-11-18 showed accounts #4/#5 due a day-15 catch-up at 14:00 EAT.
- **Daily admin report:** goes to the owner's Telegram chat through `ADMIN_TELEGRAM_CHAT_ID`, set in the server `.env` on 2026-11-24 (a test report arrived). Before that it was emailed every day at 06:00 UTC. `admin@fair.tergym.com` stays the only superuser, with no Telegram connected, as the owner wants. Check: `python manage.py shell -c "from trades.reporting import report_recipients; print(report_recipients())"` should show one chat and no emails.

### Server checks (all done 2026-11-24)
- [x] `ADMIN_TELEGRAM_CHAT_ID` set on 2026-11-24 to the owner's chat (copied from their FAIR account); a test report arrived on Telegram. Scheduled reports go there from 2026-11-25 09:00 EAT.
- [x] Catch-up sends for accounts #4/#5: each got its day-15 catch-up by email and Telegram on 2026-11-18 at 11:00 UTC (14:00 EAT), as the dry run predicted (`ReminderHistory`, `catch_up=True`).
- [x] Email delivery: SMTP through Brevo (`smtp-relay.brevo.com:587`, TLS). 47 email reminders recorded as sent, none failed, and the profile page's **Send me a test reminder** arrived (2026-11-24).
- [x] Duplicate `EMAIL_BACKEND` removed on 2026-11-24: the unused console line went, and the SMTP line (the last one, so it was already in effect) stays; `grep -c '^EMAIL_BACKEND' .env` prints 1 (checked). Backup at `.env.backup-2026-11-24`. The site answers 403 for `/.env` and the backup.
- [x] `HEALTHCHECK_PING_URL` set 2026-11-24: healthchecks.io check "FAIR reminders" (cron `0 * * * *` UTC, 30 min grace). Alerts go to Telegram through healthchecks.io's own bot (@HealthchecksBot), so FAIR's bot token isn't shared. A run that crashes pings `/fail` and alerts at once; a run that never starts (dead cron, server down, broken python) alerts after the grace time. Tested from the server: success, `/fail` and success pings all accepted, and the Telegram down and up alerts arrived.
- [x] Website monitor set up 2026-11-24: `ea3c122` deployed, `/health/` returns `ok` (200, not cached) from the server and from outside, the 5-minute cron is in, and its first ping to the healthchecks.io check "FAIR website" was accepted. Telegram alert test the same day: a `/1` then a `/0` ping gave the down and up alerts.

### Prop-firm inactivity limits (for each account's "Inactivity days")
| Firm / account | Limit |
|---|---|
| FundedNext CFD (challenge + funded) | 30 days, not extendable (help centre; no 90-day rule found) |
| FundedNext Futures (challenge + funded) | 30 calendar days incl. weekends |
| The5ers evaluation / Bootcamp | 30 days |
| The5ers Pro (funded) | 60 days |
| The5ers Futures evaluation | 14 days |

Only a trade resets the count; logging in does not. Re-check firm rules periodically.

### Firm rules that affect the FAIR Sync EA (checked 2026-11-23)
FAIR Sync never trades, so no trade is ever tagged as coming from an EA. What a broker can see is the extra investor login and its IP, so run it on the trader's own computer or network, never a VPS.

| Firm / account | Rule | FAIR Sync |
|---|---|---|
| FundedNext CFD < $50k | EAs/bots allowed; VPN/VPS allowed with conditions | OK |
| FundedNext CFD ≥ $50k | No EAs, bots or "any automated tools" (even SL/TP/lot-size tools); VPN/VPS article applies only below $50k | Ask in writing first; until then use "I traded" |
| Goat Funded Trader | Only self-written EAs (may ask for the code); from 2026-10-06 no VPN/VPS/proxy/hosting on any account | OK on own computer only; in use since 2026-11-24 |
| The5ers | EAs allowed; banned: third-party EAs without source, copy trading (mostly third-party sources) | Likely OK; confirm |

Support questions drafted 2026-11-23 for FundedNext (≥ $50k) and Goat Funded Trader, not sent yet: the FundedNext one is under "Next steps"; the Goat Funded Trader one is optional now that the GFT account syncs alongside the owner's own bot.

---

## Roadmap (plan approved 2026-11-18)

Five phases: 1 health monitoring, 2 one-tap "I traded" (email link + Telegram buttons/commands), 3 per-account inactivity limits + reminders as "days left", 4 reliable delivery (retries, catch-up, test reminder), 5 UX (urgency dashboard, .ics feed, snooze, per-user send hours). MT5 auto-sync: see "MT5 auto-sync" below (MT4 not done). WhatsApp stays hidden.

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

### Telegram: pick the date & time of a trade ✅ (2026-11-22, `5f2654b`; deployed 2026-11-23 with `46b41af`)
- `/traded` with one account now asks **[✅ Just now] [🕒 Pick date & time]** instead of recording at once; the multi-account list has both per account; reminders get a third button "🕒 Traded earlier…".
- Picker (`accounts/telegram_bot.py`): last 7 days → hour → minutes (5-min steps), in the user's timezone, future times hidden and rejected server-side. Stateless callbacks: `pick:<pk>[:<YYYYMMDD>[:<HH>]]`, `at:<pk>:<YYYYMMDD>:<HHMM>`, `menu:<pk>` (back), `noop` (header labels). Swaps only the buttons (`trades.notifications.edit_message_buttons`), so reminder text is kept; the final tap appends the confirmation like "I traded" does. Older dates: use the website.
- **Deploy:** `git pull` + restart only (no migration; `callback_query` is already registered, so no `set_telegram_webhook` re-run).

### MT5 auto-sync ✅ (2026-11-22; deployed 2026-11-23 at `46b41af`)
- **What:** the FAIR Sync Expert Advisor (`mt5/FAIR_Sync.mq5`) reports each account's newest trade **open** time; FAIR restarts the countdown from it. Closes are ignored on purpose: firms reset inactivity when a trade is *placed*, so counting from a close could show more days left than the firm gives.
- **Why an EA in an investor-password terminal:** MT5 has no public web API and cPanel can't run MT5, so data has to come from a terminal the user runs on their own computer (Windows, or Linux/Mac with Wine), not a VPS (see "Firm rules that affect the FAIR Sync EA"). **FundedNext CFD ≥ $50k bans EAs/"any automated tools"** (help article 8020763), so the EA runs in a *separate* MT5 logged in with the **investor (read-only) password**, Algo Trading off; it has no trade calls. Cloud services (MetaApi) avoided: shared IPs can trip FundedNext's group-trading/IP checks. Trades placed from phone/other PCs are still seen (history comes from the broker's server).
- **EA:** on start, on every new deal (`OnTradeTransaction`) and every 15 min (heartbeat) it finds the newest BUY/SELL deal with entry IN/INOUT, converts server time → UTC (`TimeTradeServer()-TimeGMT()` rounded to 15 min) and POSTs `{"login","server","last_open_utc","deal","ea"}` to `/api/mt5/sync/` with the key in `Authorization: Bearer` **and** `X-FAIR-Key` (some Apache/cPanel setups drop Authorization). Prints clear errors to the Experts tab (4014 or 4006 = add the site under "Allow WebRequest"). One terminal per account.
- **Server (`trades/api.py`, `mt5_sync`):** key → `User.mt5_sync_key`; login → that user's accounts with `account_number == login`; always sets `TradingAccount.mt5_last_seen`; moves `last_trade_date` **forward only** with a conditional UPDATE (an old/replayed report can't undo a newer trade recorded elsewhere), caps future times at now, clears snooze. 401 bad key, 400 bad body, 404 unknown login, 429 over 60/min per user.
- **UI:** profile "MT5 auto-sync" card (setup steps, FundedNext warning, **Download FAIR Sync EA** = `accounts:mt5_ea`, pre-filled with the site URL + user's key; "Show sync key"; "New key"). Dashboard/detail show "🔄 MT5 sync · checked in … ago" or "🔌 quiet since …" (`TradingAccount.mt5_sync_quiet`, > `MT5_QUIET_HOURS`=24h); `/status` lines end "· MT5 ✓" / "· MT5 quiet"; the daily admin report lists quiet accounts (`trades.reporting.quiet_mt5_accounts`). No Telegram message per sync (silent by choice).
- **Verified:** 249 tests pass; curl against a scratch-DB dev server: newer open → updated, older open/heartbeat → unchanged, wrong login → 404, bad key → 401. **Live demo run (2026-11-23):** MT5 build 6230 under Wine 11 on Linux, Dukascopy demo account, local FAIR at `http://127.0.0.1:8000`. The EA compiles in MetaEditor (0 errors, 0 warnings); three manual trades each reached FAIR within ~2 s and restarted the countdown; server time → UTC came out right (Dukascopy's server is GMT+2).
- **Setup gotchas (from that run):** add the FAIR URL in MT5's Tools › Options › Expert Advisors dialog. Editing `WebRequestUrl` in `Config/common.ini` only ticks the box and leaves the list empty. An unlisted IP-address URL fails with 4006, not 4014; the EA gives the allow-list hint for both. A command-line compile doesn't reload an EA already on a chart, so re-attach it. Under Wine, compile with a path relative to the MT5 folder: `wine MetaEditor64.exe '/compile:MQL5\Experts\FAIR_Sync.mq5' /log`.
- **Deploy (done 2026-11-23):** `cd /home/tergfern/fair && git pull && /home/tergfern/virtualenv/fair/3.12/bin/python manage.py migrate` (accounts 0008, trades 0010) `&& touch tmp/restart.txt`. Then on Windows (or Linux with Wine): profile → Download FAIR Sync EA → MetaEditor F7 → attach to a **demo** account first, open a trade, check FAIR's last trade time; then switch to the investor login on the real account. Set each account's *Account number* on FAIR to its MT5 login.
- **In use since 2026-11-24:** the GFT "$10K Phase 2" account (login 315004527, GoatFunded-Server) syncs from the owner's GFT trading terminal on their own computer (MT5 under Wine). FAIR Sync sits on its own chart there, next to the owner's own trading EA. A separate investor-password terminal isn't needed for this account: it's already traded by a self-written EA, which GFT allows. The first sync moved the last trade forward to 2026-11-19 14:30 UTC (25 days left). Accounts at firms that ban EAs still need the separate investor terminal. The profile card and the EA header now describe both options: a chart with no other EA, its own "Allow Algo Trading" unticked, and the terminal's Algo Trading left on for the bot.

### Website health check (`ea3c122`, deployed 2026-11-24)
- **`/health/`** (`forex_reminder/health.py`): `ok` (200) when the database answers and every migration is applied; `N unapplied migration(s)` (503) when the code is ahead of the database, as in the 2026-11-23 incident (the home page didn't show that one: it doesn't touch the database); 500 if the database is unreachable. Never cached.
- **Monitor (set up 2026-11-24):** a server cron (`*/5 * * * *`) loads it (30 s timeout, 2 retries) and pings the healthchecks.io check "FAIR website" (Simple: 5 min period, 10 min grace) with curl's exit status (`https://hc-ping.com/<uuid>/$?`), so alerts come from @HealthchecksBot like the reminder check's. Catches pending migrations, a database that's down, an app that can't start, web server or SSL problems, answers slower than 30 s, and the server going silent. Blind spots: bugs limited to one page, and problems only outside visitors hit (DNS, domain expiry).
- **Deploy:** `cd /home/tergfern/fair && git pull && /home/tergfern/virtualenv/fair/3.12/bin/python manage.py migrate && touch tmp/restart.txt` (no new migration), then `curl -s https://fair.tergym.com/health/` should print `ok`.

### Website shows the user's own timezone (2026-11-26, `826f1e1`; not yet deployed)
- **Problem:** trades are stored in UTC, and the reminders, Telegram bot, calendar feed and MT5 sync all handle timezones explicitly. But web requests ran in the server's `TIME_ZONE` (UTC):
  - pages showed times 3 hours behind Kampala;
  - the account form read a typed trade time as UTC, so a trade typed for 21:00–24:00 EAT landed on the next local day, and FAIR showed one day more than the firm gives.
- **Fix:** `UserTimezoneMiddleware` (`forex_reminder/middleware.py`, after `AuthenticationMiddleware`) runs each logged-in user's request in `User.timezone` via `timezone.override`, which switches back afterwards. Anonymous requests (Telegram webhook, MT5 sync, calendar feed, `/health/`) stay in UTC. The account form says "In your time zone: …".
- **Existing data:** nothing stored changes. Times typed on the website before the fix were saved as UTC, so after the deploy they show 3 hours later than what was typed, until the next trade replaces them or they're corrected with Edit.
- **Deploy:** `cd /home/tergfern/fair && git pull && /home/tergfern/virtualenv/fair/3.12/bin/python manage.py migrate && touch tmp/restart.txt` (no new migration).

### Deploy everything at once (phases 1–5)
In `/home/tergfern/fair`, with `python` meaning `/home/tergfern/virtualenv/fair/3.12/bin/python` (see "Server python" above): `git pull && python manage.py migrate && touch tmp/restart.txt`, then: `python manage.py set_telegram_webhook`, `python manage.py set_reminder_days 20 15 10 5 3 2 1 0`, optionally add `HEALTHCHECK_PING_URL` to `.env`, restart, then `python manage.py send_reminders --dry-run` and "Send me a test reminder" on the profile page.

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
- `mt5_sync_key` (Bearer key the FAIR Sync MT5 EA sends; regenerate on profile)
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
  - `mt5_last_seen` / `mt5_sync_quiet` (MT5 auto-sync heartbeat)

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
- Test suite (256 passing, incl. MT5 auto-sync, `/health/` and the user's timezone on web pages)
- Roadmap phases 1–5 (monitoring, one-tap traded, per-account limits, reliable delivery, UX)

### Known Limitations (Not Next Features, Just Context)
- **WhatsApp:** Currently hidden in UI (Twilio wired but needs phone validation)
- **Celery/Redis:** Optional; cron works fine without it
- **Deadline-day reminder (0 days left):** days are compared by local calendar day, so it fires even if the exact deadline passed earlier that day
- **MT5 auto-sync:** needs an MT5 terminal you keep running on your own computer (not a VPS) with the FAIR Sync EA, and the firm's rules must allow it; without it, last trade date is entered manually (or via one-tap "I traded" / the Telegram picker). MT4 not supported.

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
| `accounts/views.py` | Auth, profile, Telegram webhook, MT5 EA download | ✅ Complete |
| `trades/api.py` + `mt5/FAIR_Sync.mq5` | MT5 auto-sync endpoint + the Expert Advisor | ✅ Deployed 2026-11-23; EA compiled and run on a demo account (MT5 under Wine) |
| `trades/views.py` | Account CRUD, reminder history view | ✅ Complete |
| `forex_reminder/settings.py` | Django config, security, Celery | ✅ Complete |
| `forex_reminder/health.py` | `/health/` page for the uptime monitor | ✅ Deployed 2026-11-24 |
| `conftest.py` + test files | pytest fixtures, auth/CRUD/task tests | ✅ Complete |

---

## Quick Commands (Dev)

```bash
# Activate venv (local: one level up from the repo)
source ../forex_venv/bin/activate

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

## Deployment Checklist (for a fresh server)

All done on the live server. For a new one, run `manage.py` with that app's own virtualenv python (see "Server python" above).

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

- **Timezone correctness:** All inactivity counting done in user's local TZ (not UTC). Times are stored in UTC; web pages and forms show and read them in the user's TZ (`UserTimezoneMiddleware`). This is crucial for global users.
- **Deduplication:** Unique constraint + IntegrityError catch prevents double-sends even with concurrent cron workers. Scoped per cycle (`cycle_start`) so reminders restart after each new trade.
- **Grace window:** Late cron runs (up to 3 hours) still deliver reminders, avoiding missed notifications.
- **Later-in-day skip rule:** If user trades after the 9 AM slot, the 2 PM slot is skipped same day.
- **Webhook security:** Telegram webhook signed with `TELEGRAM_WEBHOOK_SECRET`.

---

## Next-Session Entry Point

1. **Check git log:** `git log --oneline -5` (last work on 2026-11-24); then "Next steps" at the top
2. **Review feature request:** If expanding reminder rules or adding reset/payout, read "Next Feature" above
3. **Run tests:** `pytest -v` (ensure everything still passes)
4. **Start dev server:** `python manage.py runserver`
5. **List open issues:** Search GitHub issues or code comments

**For new Claude chat:** Copy this file's first half (Tech Stack + Core Models) to avoid re-reading code.
