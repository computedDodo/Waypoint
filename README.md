# Waypoint — Starter Kit

This is the rebuild in progress. **What works end to end right now:**
the full tester/admin loop from before, plus: role-based staff accounts
(Admin/Reviewer/Finance/Support), a client portal with its own login and
campaign export, an in-app notification system (manual + automated), a
"contact admin" feedback inbox for everyone, password reset for both
testers/staff and clients, and payouts now shown in Naira (₦) throughout.

Run `python seed_admin.py` after your first migration to create the
default Admin login (`admin` / `change-this-password` — change it
immediately). Every other staff account (Reviewer, Finance, Support, or
additional Admins) is invited from **Dashboard → Staff** and sets its own
password via an emailed link. Clients get portal access the same way,
automatically, the moment you add a contact email to their record (or
resend it anytime from their client page).

## Applying this update to a database that already has real data

This is a bigger schema change than last time: new columns on `users`
(`date_of_birth`, `reset_token`, `reset_expires_at`) and `clients`
(`password_hash`, `reset_token`, `reset_expires_at`), two new campaign
statuses, and four new tables (`notifications`, `notification_recipients`,
`feedback`, `scheduler_state`). **Back up your database first:**

```bash
# MySQL example, from a PythonAnywhere Bash console
mysqldump -u yourusername -h yourusername.mysql.pythonanywhere-services.com -p 'yourusername$waypoint' > backup_$(date +%Y%m%d).sql
```

Then, same as last time:

```bash
pip install -r requirements.txt
export FLASK_APP=run.py
flask db migrate -m "roles, client portal, notifications, naira, password reset"
```

**Read the generated migration file before running upgrade** — nothing
this round touches columns with data you'd lose (it's all new
columns/tables), but it's worth 30 seconds to confirm before it runs
against a live database.

```bash
flask db upgrade
```

One manual step autogenerate can't do for you: **existing testers won't
have a `date_of_birth`** (it's now required for new registrations, but
existing rows are null). They'll just be skipped by the birthday check
until they fill it in from the new **Profile** page — nothing breaks,
they just won't get a birthday notification until then.

Reload the web app from the Web tab once it's applied.

## What changed from the old schema

- **Client** and **Campaign** are new. A campaign belongs to a client and
  holds its own status, points budget, and $-per-point conversion rate.
- **Task** now belongs to a `campaign_id` instead of a global pool.
- **Enrollment** links a tester to a specific campaign with campaign-scoped
  points, so one tester can work multiple campaigns without their scores
  mixing.
- **User.wallet_points** replaces `total_points` — it's the tester's
  redeemable balance across all campaigns, only ever changed through a
  `Transaction` row (an audit trail) or a `RedemptionRequest`.
- **Transaction** and **RedemptionRequest** are new — the payout pipeline
  the old version didn't have.

## Database: MySQL or PostgreSQL?

Set `DB_ENGINE` in `.env` to `mysql` or `postgres`.

**Recommendation: start with MySQL.** It's included free on every
PythonAnywhere account (even the free tier) and needs zero extra setup.
PythonAnywhere's own hosted Postgres only exists on paid Custom accounts,
costs extra, and — as of PythonAnywhere's own forum threads in 2026 — is
still pinned to Postgres 12, which is past its support window and
incompatible with newer versions of some libraries. If you specifically
want Postgres, the more future-proof route is an external managed Postgres
host (Neon, Supabase) reached over the internet, which also requires a
paid PythonAnywhere account for outbound network access. Either way, the
app code doesn't change — only the `.env` values do.

## Local setup

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then fill in real values
```

## PythonAnywhere deployment

1. **Upload the code.** Easiest: push this project to GitHub, then in a
   PythonAnywhere Bash console: `git clone <your-repo-url> waypoint`.
2. **Create a virtualenv** (Bash console):
   ```bash
   cd waypoint
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Create the database.** Go to the **Databases** tab, start MySQL if
   you haven't, and create a database — PythonAnywhere will name it
   `yourusername$waypoint`. Copy the host shown there into `DB_HOST`.
4. **Create `.env`** in the project root (`nano .env`, paste from
   `.env.example`, fill in real values — this file is never committed).
5. **Web tab → Add a new web app → Manual configuration → Python 3.x.**
6. **Set the virtualenv path** to `/home/yourusername/waypoint/venv`.
7. **Edit the WSGI file** PythonAnywhere links to, replacing its contents
   with `wsgi_pythonanywhere_example.py` (update the username/path).
8. **Static files mapping:** URL `/static/` → Directory
   `/home/yourusername/waypoint/static`.
9. Run migrations/`db.create_all()` from a Bash console, then hit
   **Reload** on the Web tab.

## Roles

Four staff roles, defined in `permissions.py` as a simple permission map —
not a routes rewrite if you ever want to change who can do what:

| Role | Can do |
|---|---|
| Admin | Everything — clients, campaigns, reviews, payouts, access control, staff, support |
| Reviewer | Review queue only |
| Finance | Payouts queue + master ledger |
| Support | Access control + notifications + feedback inbox |

Testers and Clients aren't "roles" in this system — they're separate
login types entirely (`session['role']` vs `session['client_id']`).

## Notifications & automation

`notifications.py` has one function, `create_notification(...)`, that
both admin-composed and automated sends go through — it fans a message
out to `NotificationRecipient` rows for whichever audience you pick (all
users, all testers, one tester, one campaign's testers, all clients, or
one client).

Automated sends run via a "lazy cron" — `run_due_automations()` fires on
every request but only actually does anything once an hour (tracked in
`scheduler_state`), checking for birthdays and missions about to expire.
No PythonAnywhere paid tier or background worker needed. New-campaign and
new-mission notifications don't wait for that hourly check at all — they
fire immediately from `campaigns.py` the moment you change a campaign to
Recruiting or add a mission to an Active one.

## Mission locking & retry rules

- A mission is exclusive the moment it's claimed — it disappears from
  everyone else's board while `Claimed` or `Submitted`.
- **Rejected** (first time): the same tester gets one retry, at
  `max(5, half the original time limit)`. Still invisible to everyone
  else while that retry window is open.
- **Rejected again on the retry, or the original claim just expires
  unsubmitted:** the mission goes fully vacant — anyone enrolled can
  claim it, including the original tester.
- **Approved:** the mission is auto-hidden for good (`is_active` flips
  off). Admin still sees it on the campaign page marked "Completed,"
  it just can't be reopened from there — flip `is_active` back on
  manually if you ever want to run it again as a fresh mission.

## What's next

1. **Ops hardening:** background email queue instead of inline
   `mail.send()`; move screenshots to S3-compatible storage instead of
   local disk.
2. **Deadline/birthday check tuning:** the lazy-cron interval is 1 hour
   (`CHECK_INTERVAL` in `notifications.py`) — fine for now, but if you
   want deadline warnings tighter than "within the hour," lower it.
3. Anything else that comes up once you're using this day to day.
