# WAYPOINT — COMPLETE OPS HANDOVER

Database / Alembic incident, repository synchronization, authentication & email verification review, and manual unverified-account cleanup remediation

**12 September 2026**

## 0. Purpose and scope

This document records the work performed on Waypoint from the PostgreSQL/Alembic incident through the current email-verification and manual stale-account-cleanup review. It is written so Operations/Engineering can continue immediately without reconstructing the investigation from the chat history.

Completed repairs are separated from proposed changes. Nothing described under the remediation plan should be assumed to have been implemented unless it appears in the completed section.

**NOTE:** The Aiven keep-alive discussion is intentionally excluded. The Aiven service power-off is recorded only because it was the actual cause of the original database connectivity incident.

## 1. Project identity and source

- **Project:** Waypoint
- **GitHub repository:** computedDodo/waypoint
- **Remote observed locally:** git@github.com:computedDodo/waypoint
- **Primary branch:** main
- **Production database:** PostgreSQL hosted on Aiven
- **Application:** Flask + SQLAlchemy + Flask-Migrate/Alembic
- **Repository:** https://github.com/computedDodo/waypoint

## 2. Executive status

- **Aiven PostgreSQL connectivity** — RECOVERED — The user manually powered the service back on; connectivity was subsequently verified.
- **Alembic revision mismatch** — REPAIRED — Production had 902742dc3536 while the repository head was 12f0667e4f45.
- **Current migration state** — CLEAN — flask db current reports 12f0667e4f45 (head).
- **Schema comparison** — CLEAN — Autogenerate returned No changes in schema detected.
- **GitHub/local sync checkpoint** — VERIFIED — HEAD and origin/main were both 8d34a36; diff stat was empty.
- **Manual user cleanup** — REVIEWED — Route/button are wired; current rule is 24h+ Pending Email, with weak error handling.
- **Email verification** — REVIEWED — Current system randomly chooses OTP, token, or both; resend ordering needs improvement.

## 3. PostgreSQL/Aiven incident

### 3.1 Initial error

```
flask db current
psycopg2.OperationalError: could not translate host name "waypoint-waypoint-6923.b.aivencloud.com" to address: No address associated with hostname
```

The user subsequently confirmed the Aiven PostgreSQL service had been powered off after days of inactivity and manually powered it back on. After it was powered on, database access progressed far enough to expose the separate Alembic problem.

### 3.2 Second error: stale/missing Alembic revision

```
flask db current
ERROR [flask_migrate] Error: Can't locate revision identified by '902742dc3536'
```

This established that the database was reachable, but its alembic_version pointed to a revision that the current repository no longer contained.

## 4. Migration-state investigation

### 4.1 Live database marker

```python
SELECT version_num FROM alembic_version;
[('902742dc3536',)]
```

Production therefore believed it was at revision 902742dc3536.

### 4.2 Repository migration head

```
flask db heads
12f0667e4f45 (head)

flask db history
<base> -> 12f0667e4f45 (head), Initial postgres schema
```

### 4.3 Search for missing revision

```
grep -R "902742dc3536" migrations . --exclude-dir=.git --exclude="*.pyc"
```

No result was found.

### 4.4 Git history explanation

Git history identified commit 4f2727f7b9e28ecf999a5b74248d5acc08f8c4e4:

```
Reset migration history for production Postgres
```

That commit introduced 12f0667e4f45_initial_postgres_schema.py and deleted the older bd52bb41fb15_roles_client_portal_notifications_naira_.py. The repository migration history was therefore deliberately reset, while production's alembic_version still retained the old revision 902742dc3536.

This was a migration-bookkeeping mismatch, not evidence by itself that the production tables were missing.

### 4.5 Live schema inspection

The live PostgreSQL schema was inspected. Expected application tables were present, and the production tasks table included tasks.prerequisite_task_id. This was important because it showed the live database already contained later application schema represented by the current models.

## 5. Migration repair

### 5.1 Normal stamp attempt — failed

```
flask db stamp 12f0667e4f45
ERROR [flask_migrate] Error: Can't locate revision identified by '902742dc3536'
```

A normal stamp was insufficient because Alembic still attempted to resolve the stale revision.

### 5.2 Successful repair

```
flask db stamp --purge 12f0667e4f45
INFO [alembic.runtime.migration] Running stamp_revision  -> 12f0667e4f45
```

This purged the stale Alembic revision marker and stamped the database to the verified repository baseline.

### 5.3 Verification

```
flask db current
12f0667e4f45 (head)
```

## 6. Schema verification after repair

### 6.1 Temporary connectivity check

```
ping -c 1 waypoint-waypoint-6923.b.aivencloud.com
PING waypoint-waypoint-6923.b.aivencloud.com (159.223.215.178) ...
0% packet loss
```

The host was reachable.

### 6.2 Alembic autogenerate comparison

```
flask db migrate --message "SCHEMA_CHECK"
INFO [alembic.env] No changes in schema detected.
```

No migration file was created. This is the critical confirmation that the current models and live database produced no detected schema difference.

### 6.3 Git status recorded after the check

```
git status --short
 M .env
?? seed.py
?? seed_template.py
?? wipe_tasks.py
```

**NOTE:** Do not expose .env contents. The seed/template/wipe files were understood to be intentional project utilities and should be preserved.

## 7. Repository synchronization checkpoint

```
origin git@github.com:computedDodo/waypoint.git
main 8d34a36 (HEAD -> main, origin/main)

git diff HEAD origin/main --stat
# empty output
```

At the checkpoint, local HEAD and origin/main were synchronized at 8d34a36.

Before any new changes, Ops should repeat the status/log/remote checks rather than blindly replacing local files with GitHub copies.

## 8. Migration rules going forward

- **Verified baseline/head:** 12f0667e4f45.
- Do not manually edit alembic_version.
- Do not delete/reset migration history as a routine fix.
- Do not generate migrations for Python/template-only changes.
- Create a migration only when an actual database/model schema change is introduced.

### 8.1 Normal future migration workflow

1. Modify the SQLAlchemy model for the intended schema change.
2. `flask db migrate -m "describe the schema change"`
3. Inspect the generated migration before applying it.
4. Commit the model change and migration together.
5. Deploy.
6. `flask db upgrade`
7. `flask db current`
8. `flask db migrate --message "SCHEMA_CHECK"` (optional verification; do not keep an empty generated migration)

## 9. Active application architecture

- **run.py → app.py** is the active launch path.
- **auth.py:** registration, login, verification, resend verification, password reset.
- **admin.py:** admin dashboard and stale Pending Email cleanup.
- **models.py:** SQLAlchemy models, including User, Task and SchedulerState.
- **notifications.py:** lazy notification/automation scheduler.
- **config.py:** database and Flask-Mail configuration.
- **templates/auth/verify.html:** verification UI.
- **admin1.py, models1.py, app1.py, tasks1.py and base1.html** are legacy/backup copies; do not change them instead of active files.

## 10. Email verification — current behavior

### 10.1 Registration

```python
verification_method = random.choice(['otp', 'token', 'both'])
new_user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)
Message(subject="Verify your Waypoint account", recipients=[email], body=email_body)
```

Registration may therefore send OTP only, link only, or both. The verification window is 15 minutes.

If initial registration email sending fails, the current registration path deletes the newly created user and commits that deletion, preventing that particular failed-send path from leaving an unusable new account.

### 10.2 User verification fields

```python
verification_token = db.Column(db.String(100), unique=True, nullable=True)
verification_otp = db.Column(db.String(6), nullable=True)
verification_expires_at = db.Column(db.DateTime, nullable=True)
```

The model generates a six-digit OTP and a URL-safe token using Python's secrets module.

### 10.3 OTP route

```python
if submitted_otp and submitted_otp == user.verification_otp:
    user.verification_otp = None
    user.verification_token = None
```

The route also checks expiry. Ops should verify the exact commit/state update in the active auth.py before finalizing changes.

### 10.4 Link route

```python
User.query.filter_by(verification_token=token).first()
```

The link route validates the token and expiry and clears the OTP/token after successful verification.

### 10.5 Resend verification — identified reliability issue

The resend route regenerates credentials, resets expiry, and currently commits before attempting mail delivery. Therefore an SMTP/mail failure can leave the database holding new credentials that the user never received.

```python
db.session.commit()
# then mail.send(...)
```

This is a concrete bug/UX reliability issue to fix.

### 10.6 Verification template

The active verification UI supports both possible methods, telling the user they may have received a six-digit code or a verification link. Because the backend randomly chooses the method, the UX is nondeterministic.

## 11. Recommended email-verification solution

- Always issue BOTH a verification link and a six-digit OTP. Remove random.choice(['otp','token','both']).
- Use one shared 15-minute expiry for both mechanisms.
- Successful verification invalidates both credentials.
- Resend invalidates the old pair only according to a safe transaction design.
- Do not leave an account stranded with newly committed credentials if mail delivery fails.
- Add resend rate limiting/abuse protection.
- Verify _external=True generates the real public deployed Waypoint host.
- Test actual delivery from the deployed environment without exposing SMTP secrets.

## 12. Flask-Mail configuration observed

```python
MAIL_SERVER = os.environ.get('MAIL_SERVER')
MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
```

Mail sending is also used by other active modules such as clients.py, client_portal.py and admin.py, so SMTP configuration changes can affect more than registration verification.

## 13. Manual unverified-account cleanup — current behavior

### 13.1 Architecture

Cleanup is a MANUAL ADMIN DASHBOARD ACTION. It is not automatic. The lazy scheduler in notifications.py is unrelated to deleting unverified users.

### 13.2 Active route

```python
@admin_bp.route('/cleanup-stale-accounts', methods=['POST'])
def cleanup_stale():
```

The route requires the application's management permission and flashes a message such as:

```
flash(f'Cleaned up {count} stale unverified accounts.', 'success')
```

### 13.3 Current eligibility rule

```python
threshold = datetime.utcnow() - timedelta(hours=24)

stale_users = User.query.filter(
    User.account_status == 'Pending Email',
    User.created_at < threshold
).all()
```

This means a Pending Email account created one hour ago will NOT be deleted, even if its 15-minute verification window has expired. The current rule is age-based at 24 hours, not simply token-expiry-based.

This is a likely explanation for the observed impression that the cleanup button 'doesn't work' when the account is newer than 24 hours.

### 13.4 Current deletion behavior

```python
db.session.delete(user)
db.session.commit()
```

The current implementation needs stronger transaction/error handling. A related foreign-key/integrity error could make the commit fail. The administrator should receive a truthful result and the session should be rolled back on failure.

## 14. Recommended cleanup solution

### 14.1 Keep it manual

Do not introduce automatic deletion unless separately approved. Keep the admin dashboard button as the trigger.

### 14.2 Recommended eligibility

- `account_status == 'Pending Email'`
- `AND verification window has expired`
- `AND account age >= 24 hours`

This combines actual verification expiry with a 24-hour safety period.

### 14.3 Recommended admin UX

The pending-user page should show why an account is or is not eligible. Suggested columns:

```
Username | Email | Registered | Verification status | Cleanup eligibility
```

The button should clearly state its rule, for example:

```
Clean up expired accounts (24h+)
```

If none qualify, show a clear message such as:

```
No expired Pending Email accounts older than 24 hours were found.
```

### 14.4 Recommended transaction handling

1. Query eligible users.
2. Stage deletions.
3. Commit once.
4. On exception, rollback.
5. Log the server-side exception.
6. Show a safe administrator-facing error.
7. Do not report success if the transaction failed.
8. Ensure verified or Pending Approval accounts can never be selected.

## 15. Login/account-state observation

The current login flow establishes session information after password authentication before all account-state restrictions are completely enforced. This is not being treated as the cause of the cleanup issue, but it is cleaner to validate account lifecycle state before establishing the normal application session.

**Recommended sequence:**

1. Find user.
2. Validate password.
3. Validate account status / verification state.
4. Establish authenticated application session.

Ops should verify the intended Waypoint lifecycle states before changing this logic.

## 16. Scheduler architecture — do not confuse with cleanup

models.py contains SchedulerState, described as the small table backing the lazy cron in notifications.py.

```python
last_run_at = db.Column(db.DateTime, default=datetime(2000, 1, 1))
```

app.py invokes the automation check from a before_request hook; notifications.py uses a CHECK_INTERVAL. This is notification/automation logic, not stale-user cleanup.

## 17. Task schema detail observed

```python
prerequisite_task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True)
```

The live database contained this field during schema inspection. The successful Alembic autogenerate result is the authoritative checkpoint used in this investigation: No changes in schema detected.

## 18. Search commands used during code investigation

```bash
grep -RniE "verification|verify|verification_token|verification_otp|verification_expires" . --include="*.py" --exclude-dir=.git --exclude="*.pyc"
grep -RniE "unverified|cleanup|clean.?up|delete.*user|user.*delete|purge" ...
grep -RniE "mail\.send|Message\(|send_mail|SMTP|MAIL_" ...
grep -RniE "scheduler|scheduled|cron|lazy|last_run_at|before_request|after_request"
find . -maxdepth 2 -type f -not -path './.git/*' -not -path './__pycache__/*' | sort
```

## 19. Completed work

- ✓ Aiven PostgreSQL service was manually powered back on by the user.
- ✓ Database connectivity was restored sufficiently for inspection.
- ✓ Production alembic_version was identified as 902742dc3536.
- ✓ Repository migration head was identified as 12f0667e4f45.
- ✓ The missing revision was confirmed absent from the current migration tree.
- ✓ Git history was inspected and the migration-history reset was identified.
- ✓ Live schema was inspected.
- ✓ Normal flask db stamp failed because the old revision could not be resolved.
- ✓ flask db stamp --purge 12f0667e4f45 succeeded.
- ✓ flask db current confirmed 12f0667e4f45 (head).
- ✓ DNS/connectivity was verified with ping.
- ✓ flask db migrate --message SCHEMA_CHECK returned No changes in schema detected.
- ✓ No schema migration was generated by the check.
- ✓ Local/GitHub synchronization was verified at 8d34a36 at the recorded checkpoint.
- ✓ Active cleanup route/button wiring was traced.
- ✓ Email verification and resend flows were traced.
- ✓ Concrete remediation plans were established for email verification and manual cleanup.

## 20. Not yet implemented — Ops work queue

- ☐ Standardize verification to always send OTP + link.
- ☐ Fix resend transaction/error behavior.
- ☐ Consider resend rate limiting.
- ☐ Verify public host generation for verification links.
- ☐ Improve pending-user cleanup visibility.
- ☐ Improve cleanup eligibility messaging.
- ☐ Improve cleanup transaction/rollback/error handling.
- ☐ Review account-state checks before session creation.
- ☐ Run end-to-end registration/email/verification/cleanup tests.
- ☐ Only create a migration if a genuine schema change is introduced.

## 21. End-to-end acceptance checklist

- ☐ Registration creates Pending Email.
- ☐ Verification email is delivered.
- ☐ Email contains both link and six-digit OTP.
- ☐ Link verification succeeds before expiry.
- ☐ OTP verification succeeds before expiry.
- ☐ Successful verification changes the correct account state.
- ☐ Successful verification clears both OTP and token.
- ☐ Expired OTP is rejected.
- ☐ Expired link is rejected.
- ☐ Resend works and invalidates old credentials appropriately.
- ☐ Failed resend does not strand the account with credentials the user cannot receive.
- ☐ Recent Pending Email users are not cleaned up.
- ☐ Expired Pending Email users older than 24h are eligible.
- ☐ Admin cleanup POST is protected by CSRF/permission checks.
- ☐ Cleanup deletes eligible users.
- ☐ Cleanup reports zero eligible accounts clearly.
- ☐ Cleanup failure rolls back and reports failure truthfully.
- ☐ Verified/Pending Approval users cannot be cleaned up.
- ☐ Pending Email users cannot access protected areas.
- ☐ Production verification link uses the real public host.
- ☐ flask db current remains 12f0667e4f45 unless an intentional migration changes it.
- ☐ Schema check produces no unexpected changes.

## 22. Operational cautions

- ⚠️ Never expose .env values, database passwords, SMTP passwords, secret keys, or API tokens.
- ⚠️ Never manually edit alembic_version as a routine repair.
- ⚠️ Never use stamp --purge casually; the command was used here only after verifying the live schema and stale revision state.
- ⚠️ Never delete migration files simply to make Alembic stop complaining.
- ⚠️ Do not create empty migrations.
- ⚠️ Do not modify legacy *1 files instead of the active files.
- ⚠️ Do not assume cleanup is automatic.
- ⚠️ Do not interpret a zero cleanup count as proof of a broken button; inspect eligibility first.
- ⚠️ Always re-check git status and local-vs-origin state before applying changes.

## 23. One-page technical diagnosis

The database incident had two layers. First, the Aiven PostgreSQL service was powered off after inactivity, producing the hostname/connectivity error. After the user manually powered it on, the application reached PostgreSQL and exposed the Alembic mismatch: production recorded 902742dc3536 while the repository had deliberately reset migration history and used 12f0667e4f45 as its baseline. Live schema inspection showed the application tables were present, including later structure such as tasks.prerequisite_task_id. Because the schema matched the current models, the safe repair was to purge the stale revision marker and stamp the verified baseline: flask db stamp --purge 12f0667e4f45. Verification then showed 12f0667e4f45 (head), and Alembic autogenerate returned No changes in schema detected.

The separate application review found that email verification is unnecessarily nondeterministic because registration/resend randomly choose OTP, token, or both. The resend path can also commit new verification credentials before the email is successfully sent. The recommended design is deterministic OTP + link verification with safe resend transaction handling.

The manual cleanup architecture itself is correctly wired. The main behavioral issue is the current eligibility rule: Pending Email accounts must be at least 24 hours old according to created_at. A one-hour-old account whose 15-minute verification window has expired is therefore intentionally not removed. Cleanup also needs stronger rollback/error handling and clearer admin feedback.

## 24. Final handover state

Operations can continue from this document without repeating the database repair. Migration bookkeeping is repaired and verified. The next engineering task is application-level remediation of email verification and manual stale-account cleanup, followed by the acceptance tests above. The migration baseline must remain 12f0667e4f45 unless a genuine schema change is introduced.

**NOTE:** The Aiven keep-alive topic is intentionally absent, as requested.