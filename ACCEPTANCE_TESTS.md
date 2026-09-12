# Waypoint Email Verification & Cleanup — Acceptance Test Checklist

**Date:** 12 September 2026  
**Reference:** OPS_HANDOVER.md Section 21  
**Baseline Migration:** 12f0667e4f45

---

## Pre-Test Setup

- [ ] Database is running on Aiven and `flask db current` returns `12f0667e4f45 (head)`
- [ ] Flask-Mail configuration is loaded and points to a valid test/staging SMTP server
- [ ] Application is running with `python run.py` or deployed to staging
- [ ] Admin user account exists and can access `/admin/pending-users`
- [ ] Test database is clean or contains known test user accounts

---

## Part 1: Registration & Email Delivery

### Registration Flow

- [ ] Navigate to `/register` and complete a new registration with valid data
  - username: `testuser_[timestamp]`
  - email: `test+[timestamp]@example.com`
  - password: valid 8+ char password
  - date_of_birth: valid date
- [ ] User is created with `account_status = 'Pending Email'`
- [ ] User is redirected to `/verify?email=[email]`
- [ ] Verification email is delivered to the test email address
- [ ] Email delivery does NOT fail the registration (no database rollback)

### Email Content Verification

- [ ] Email subject is "Verify your Waypoint account"
- [ ] Email body contains BOTH:
  - [ ] A 6-digit OTP code (e.g., "Your verification code is: 123456")
  - [ ] A verification link (e.g., "Click the link below to verify your account: http://...") with valid token
- [ ] Both OTP and link are generated from the SAME user record
- [ ] Both OTP and link share the SAME 15-minute expiry window

---

## Part 2: OTP Verification

### Valid OTP Path

- [ ] Copy the 6-digit OTP from the email
- [ ] On the `/verify?email=...` page, enter the OTP into the input field
- [ ] Click "Verify code"
- [ ] OTP is validated against `user.verification_otp`
- [ ] User's `account_status` changes to `'Pending Approval'`
- [ ] User's `verification_otp` is cleared (set to NULL)
- [ ] User's `verification_token` is cleared (set to NULL)
- [ ] User is redirected to `/login` with success message: "Email verified! Your account is now waiting for admin approval."

### Expired OTP

- [ ] Wait for the 15-minute expiry window to pass (or manually set `verification_expires_at` to past time in DB)
- [ ] Try to submit the same OTP
- [ ] Error message: "Your verification code has expired. Please request a new one."
- [ ] User is redirected back to `/verify?email=...`

### Invalid OTP

- [ ] Submit an OTP that does not match `user.verification_otp` (e.g., "000000")
- [ ] Error message: "Invalid OTP code. Try again."
- [ ] User stays on `/verify` page
- [ ] No account state change occurs

---

## Part 3: Link Verification

### Valid Link Path

- [ ] Create a new test user and let the email arrive
- [ ] Extract the verification link from the email (should be `/verify/[token]`)
- [ ] Click or navigate to the link directly
- [ ] User's `account_status` changes to `'Pending Approval'`
- [ ] User's `verification_otp` is cleared (set to NULL)
- [ ] User's `verification_token` is cleared (set to NULL)
- [ ] User is redirected to `/login` with success message: "Email verified successfully! Your account is now waiting for admin approval."

### Expired Link

- [ ] Create a new test user and extract the token
- [ ] Manually set `verification_expires_at` to a past datetime in the database
- [ ] Visit the `/verify/[token]` link
- [ ] Error message: "Your verification link has expired. Please request a new one."
- [ ] User is redirected to `/verify?email=...`

### Invalid Token

- [ ] Visit a completely fabricated `/verify/[invalid_token]` URL
- [ ] Error message: "Invalid or expired verification link."
- [ ] User is redirected to `/register`

---

## Part 4: Resend Verification

### Resend Success

- [ ] Create a new test user and complete registration
- [ ] On the `/verify?email=...` page, click "Resend verification"
- [ ] New email arrives with:
  - [ ] A NEW 6-digit OTP (different from the first)
  - [ ] A NEW verification link (different token)
  - [ ] Same 15-minute expiry window
- [ ] Old OTP and old link are invalidated (new verification requires new credentials)
- [ ] Flash message: "A new verification step has been sent to your email."
- [ ] User stays on `/verify` page

### Resend Rate Limiting

- [ ] Click "Resend verification" multiple times in rapid succession
- [ ] Second resend (within 60 seconds) is rejected with warning: "Please wait X seconds before resending."
- [ ] No new email is sent on the blocked resend attempt
- [ ] After 60 seconds, resend is allowed again

### Resend on Mail Failure

- [ ] Temporarily misconfigure MAIL_SERVER or MAIL_PASSWORD to simulate SMTP failure
- [ ] Click "Resend verification"
- [ ] Mail delivery fails
- [ ] Error message: "Failed to resend email. Please try again later."
- [ ] User is redirected back to `/verify?email=...`
- [ ] **CRITICAL:** Database still contains OLD credentials (no new OTP/token was committed)
- [ ] User can still verify using the OLD credentials (if not yet expired)
- [ ] Restore MAIL configuration and retry resend

---

## Part 5: Login & Account State Enforcement

### Login with Pending Email

- [ ] Create a new test user but do NOT verify the email
- [ ] Try to log in with the correct username and password
- [ ] Login succeeds password validation but FAILS account state check
- [ ] User is NOT added to session
- [ ] Error message: "Account not yet verified. Please check your email."
- [ ] User is redirected to `/verify?email=...`

### Login with Pending Approval

- [ ] Verify a user's email (so `account_status = 'Pending Approval'`)
- [ ] Try to log in with correct credentials
- [ ] Login succeeds password validation
- [ ] User is added to session
- [ ] If user has staff role, redirect to `/admin/dashboard`
- [ ] If user is a Tester, show message: "Account status: Pending Approval. Please wait for admin approval."
- [ ] User is redirected back to `/login`

### Login with Active

- [ ] Have an admin approve the test user (change status to `'Active'`)
- [ ] Log in with correct credentials
- [ ] User is added to session
- [ ] If Tester role, redirect to `/tasks/bounty_board` or appropriate user dashboard
- [ ] If staff role, redirect to `/admin/dashboard`

---

## Part 6: Admin Cleanup Interface

### Pending Users Page

- [ ] Navigate to `/admin/pending-users` as an admin
- [ ] Page displays two sections:
  - [ ] "Pending Approval" users (verified, awaiting admin decision)
  - [ ] "Pending Email" users (unverified, with eligibility indicators)

### Eligibility Display

For each Pending Email user, the page shows:
- [ ] Username
- [ ] Email
- [ ] Registered timestamp
- [ ] Verification expiry timestamp
- [ ] **Eligibility status** with reason, e.g.:
  - [ ] ✓ "Eligible: expired verification + 24h+ old"
  - [ ] ✗ "Verification window still open (14 min remaining)"
  - [ ] ✗ "Account too new (22h until eligible)"

### Cleanup Button

- [ ] Button is clearly labeled: "Clean up expired accounts (24h+)"
- [ ] Button is only visible or enabled when at least one account is eligible
- [ ] Button triggers a POST to `/admin/cleanup-stale-accounts`

---

## Part 7: Manual Cleanup Logic

### No Eligible Accounts

- [ ] Ensure no Pending Email accounts have both:
  - verification window expired AND
  - account age >= 24 hours
- [ ] Click "Clean up expired accounts (24h+)"
- [ ] Message: "No expired Pending Email accounts older than 24 hours were found."
- [ ] No accounts are deleted

### One Eligible Account

- [ ] Create a new test user
- [ ] Manually set `verification_expires_at` to 15 minutes ago
- [ ] Manually set `created_at` to 25 hours ago
- [ ] Click "Clean up expired accounts (24h+)"
- [ ] Message: "✓ Cleaned up 1 stale unverified account(s)."
- [ ] User is deleted from database
- [ ] Account is no longer visible on pending-users page

### Multiple Eligible Accounts

- [ ] Create 3 test users with stale eligibility (expired + 24h+ old)
- [ ] Click "Clean up expired accounts (24h+)"
- [ ] Message: "✓ Cleaned up 3 stale unverified account(s)."
- [ ] All 3 users are deleted
- [ ] None of the accounts are visible on pending-users page

### Recent Pending Email Not Deleted

- [ ] Create a new test user
- [ ] Manually set `verification_expires_at` to 15 minutes ago (verification expired)
- [ ] Keep `created_at` at current time (account is new, < 24 hours)
- [ ] Click "Clean up expired accounts (24h+)"
- [ ] Message: "No expired Pending Email accounts older than 24 hours were found."
- [ ] The user is NOT deleted
- [ ] User is still visible on pending-users page with eligibility reason: "Account too new"

### Verified/Pending Approval Not Deleted

- [ ] Create a test user with `account_status = 'Pending Approval'`
- [ ] Manually set `created_at` to 25 hours ago
- [ ] Click "Clean up expired accounts (24h+)"
- [ ] Message: "No expired Pending Email accounts older than 24 hours were found."
- [ ] The account is NOT deleted (cleanup only targets Pending Email)
- [ ] Account remains on pending-users page in the "Pending Approval" section

### Cleanup Transaction Failure (Error Handling)

- [ ] Simulate a database constraint violation (e.g., corrupt foreign key)
- [ ] Click "Clean up expired accounts (24h+)"
- [ ] Transaction fails
- [ ] Error message: "❌ Cleanup failed. An error occurred: [error details]. Please check logs."
- [ ] No accounts are deleted (rollback successful)
- [ ] All targeted accounts remain visible on pending-users page
- [ ] Error is logged with full traceback

---

## Part 8: Database State Verification

### Schema Check

- [ ] Run `flask db migrate --message "SCHEMA_CHECK"`
- [ ] Output: "INFO [alembic.env] No changes in schema detected."
- [ ] No migration file is created
- [ ] Run `flask db current`
- [ ] Output: `12f0667e4f45 (head)`

### Verification Fields

- [ ] Query a Pending Email user: `User.query.get(id).verification_otp` is a string (6 digits)
- [ ] Query a Pending Email user: `User.query.get(id).verification_token` is a string (URL-safe token)
- [ ] Query a Pending Email user: `User.query.get(id).verification_expires_at` is a datetime
- [ ] Query a verified user: all three fields are NULL

### Cleanup Audit

- [ ] Check database logs or application logs for cleanup events
- [ ] Log entries contain: count of deleted accounts, timestamp, user who triggered cleanup
- [ ] Log entries do NOT expose any sensitive user data (passwords, tokens, etc.)

---

## Part 9: Public Host Verification

### Verification Link Host

- [ ] Register a new user
- [ ] Inspect the verification email link
- [ ] Link uses the real deployed/public host, NOT localhost
  - Expected: `https://waypoint.example.com/verify/[token]`
  - NOT: `http://localhost:5000/verify/[token]`
- [ ] Link is clickable and resolves to the correct page

### Flask `_external=True` Configuration

- [ ] Check `config.py` or environment for `SERVER_NAME` or similar
- [ ] Verify that `url_for(..., _external=True)` generates the correct public URL
- [ ] Test in both development and staging/production environments

---

## Part 10: Email Configuration & Secrets

### No Secrets in Logs

- [ ] Check application logs for cleanup/verification operations
- [ ] Logs do NOT contain:
  - [ ] MAIL_PASSWORD
  - [ ] MAIL_USERNAME
  - [ ] SMTP credentials
  - [ ] User passwords (hashed only)
  - [ ] User tokens (only counts/timestamps)

### No Secrets in Error Messages

- [ ] Trigger a mail failure and view the error message
- [ ] User-facing message is generic: "Failed to resend email. Please try again later."
- [ ] Admin/server logs contain the actual error for debugging

---

## Part 11: End-to-End Happy Path

**Scenario: Complete registration → verification → login → access**

1. [ ] Navigate to `/register`
2. [ ] Fill in registration form with valid data
3. [ ] Submit
4. [ ] Receive email with OTP and link
5. [ ] Click the verification link in email
6. [ ] User is redirected to login with success message
7. [ ] Log out (if auto-logged-in) or stay on login page
8. [ ] Admin navigates to `/admin/pending-users` and approves the user
9. [ ] User logs in with username and password
10. [ ] User is redirected to bounty board or user dashboard
11. [ ] User can access protected pages (e.g., view tasks, claim tasks)
12. [ ] Logout and re-login works as expected

---

## Part 12: Database Migration Integrity

### No Accidental Migrations

- [ ] Run `flask db migrate --message "TEST_CHECK"` at any time
- [ ] Output: "No changes in schema detected."
- [ ] No new migration file is generated
- [ ] `flask db current` still reports `12f0667e4f45 (head)`

### Manual Timestamp Manipulation

- [ ] Modify `created_at` or `verification_expires_at` for a test user using raw SQL
- [ ] Cleanup logic correctly interprets the manual timestamps
- [ ] Eligibility calculation is accurate based on modified times

---

## Part 13: Operational Cautions Verification

- [ ] ✓ `.env` file is never printed in logs or error messages
- [ ] ✓ No manual `alembic_version` edits are performed
- [ ] ✓ Baseline migration `12f0667e4f45` remains unchanged unless a schema change is intentionally introduced
- [ ] ✓ No empty migrations are created
- [ ] ✓ Legacy files (`auth1.py`, `models1.py`, etc.) are not modified or used
- [ ] ✓ Cleanup is NOT automatic and requires manual admin button click
- [ ] ✓ Zero cleanup count is clearly explained (eligibility reasons shown)

---

## Test Results Summary

| Test Area | Status | Notes |
|-----------|--------|-------|
| Registration & Email | ☐ PASS / ☐ FAIL | |
| OTP Verification | ☐ PASS / ☐ FAIL | |
| Link Verification | ☐ PASS / ☐ FAIL | |
| Resend Logic | ☐ PASS / ☐ FAIL | |
| Login State Checks | ☐ PASS / ☐ FAIL | |
| Cleanup Eligibility | ☐ PASS / ☐ FAIL | |
| Cleanup Deletion | ☐ PASS / ☐ FAIL | |
| Error Handling | ☐ PASS / ☐ FAIL | |
| Schema Integrity | ☐ PASS / ☐ FAIL | |
| Public Host Config | ☐ PASS / ☐ FAIL | |
| End-to-End Flow | ☐ PASS / ☐ FAIL | |
| Migration Baseline | ☐ PASS / ☐ FAIL | |

---

## Sign-Off

- **Tested by:** ___________________
- **Date:** ___________________
- **Overall Result:** ☐ PASS / ☐ FAIL
- **Issues Found:** (list any failing tests)

---

**Reference Documents:**
- OPS_HANDOVER.md (Section 21 — End-to-end acceptance checklist)
- auth.py (registration, verification, resend)
- admin.py (cleanup logic)
- models.py (User model, verification fields)
- config.py (Flask-Mail configuration)
