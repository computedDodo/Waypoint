# 📋 WAYPOINT GRPMS BETA: PLATFORM STABILIZATION & INFRASTRUCTURE REPORT
**Date:** September 13, 2026
**Environment:** Render (Production) / Termux (Local)
**Status:** ALL ISSUES RESOLVED

---

## 1. Executive Summary
This document serves as the final technical record for the stabilization of the Waypoint platform ahead of the GRPMS Beta season. It covers the resolution of PostgreSQL database constraints, the implementation of application-level network timeouts, the complete migration from SMTP to the Brevo HTTP API to bypass Render's firewall, and the secure synchronization of the local Termux environment.

---

## 2. Database Constraints: Stale Account Cleanup
### 2.1 The Issue
Triggering the `cleanup-stale-accounts` route in `/admin/pending-users` resulted in a critical database exception:
> `psycopg2.errors.ForeignKeyViolation: update or delete on table "users" violates foreign key constraint`

### 2.2 The Investigation & Fix
Using Aiven's PostgreSQL console, we queried `information_schema.table_constraints` and identified that unverified accounts (e.g., `theDoer` and `Jidderh`) had dependent records generated in the `notifications` and `notification_recipients` tables. 

Instead of applying global cascading deletes, a surgical cleanup was added to `admin.py` to clear dependent records *before* deleting the user row:
```python
# admin.py (inside cleanup_stale)
from models import NotificationRecipient, Notification

NotificationRecipient.query.filter_by(user_id=user.id).delete()
Notification.query.filter_by(target_user_id=user.id).delete()
Notification.query.filter_by(sender_staff_id=user.id).delete()

db.session.delete(user)

3. Network Hangs & SMTP Port Blocking
3.1 The Issue
Clicking "Resend verification" resulted in an infinite loading screen on the UI, eventually failing silently. Once a strict 10-second global socket timeout was forced in auth.py (socket.setdefaulttimeout(10.0)), the true Render logs were exposed:
> Registration email failed for [email]: [Errno 101] Network is unreachable
> 
3.2 The Root Cause
Render strictly blocks all outbound SMTP traffic (Ports 25, 465, 587) on its Free Web Service tier. The Gunicorn worker was hanging indefinitely waiting for a network handshake that the firewall was actively dropping.
4. Email Infrastructure Migration (Brevo API)
To bypass the firewall without upgrading infrastructure costs, the platform was migrated from Flask-Mail to standard HTTPS requests using the Brevo v3 API.
4.1 Codebase Refactoring
 * Utility Creation: Created a centralized email_utils.py file utilizing the requests library to construct and dispatch API payloads with a hard 10-second timeout to prevent future Gunicorn freezes.
 * Dependency Removal: Completely removed Flask-Mail initialization from app.py.
 * Route Updates: Replaced all mail.send(msg) logic with send_brevo_email() across the following files:
   * auth.py
   * admin.py
   * clients.py
   * client_portal.py
 * Dependencies: Added requests to requirements.txt.
4.2 Render Environment Variable Fixes
During initial deployment, the Brevo API threw an immediate 400 Bad Request error. Two critical environment variable misconfigurations were identified and patched in the Render Dashboard:
 * Missing Key: Added BREVO_API_KEY to prevent the ValueError.
 * Malformed Sender: MAIL_DEFAULT_SENDER contained bracketed formatting (Waypoint <...gmail.com>) which broke the JSON payload. This was sanitized to purely the raw email string.
Result: Registration and verification emails are now successfully delivered instantly.
5. Local Environment Synchronization (Termux)
Following the successful deployment and testing on the live Render environment, the local Termux environment was securely synced.
5.1 Security Considerations
The local directory contained uncommitted, sensitive, or temporary files (.env, seed.py, seed_template.py, wipe_tasks.py) that needed to be preserved and protected from Git overwrite conflicts.
5.2 Synchronization Workflow executed in Termux:
~/waypoint_starter_kit $ git stash
Saved working directory and index state WIP on main: 8d34a36 Add files via upload

~/waypoint_starter_kit $ git pull origin main
# Pulled 57 objects, fast-forwarding 8d34a36..0e87d4a
# Included creation of email_utils.py, updates to core logic, and deletion of deprecated files (admin1.py, tasks1.py).

~/waypoint_starter_kit $ git stash pop
# Successfully restored uncommitted .env and utility scripts to the working directory.

5.3 Finalizing Local Setup
To ensure the local Termux environment can execute the new Brevo API logic, the newly added requests library was installed:
pip install -r requirements.txt

Status: The Waypoint platform codebase is fully synced across environments, database constraints are handled safely, and email communications are operational over standard HTTP protocols. Ready for continuous development of the GRPMS Beta season.


