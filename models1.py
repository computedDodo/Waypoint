from datetime import datetime
import secrets
import string
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class Client(db.Model):
    """A paying customer who commissions beta-testing campaigns. Can log
    into the read-only client portal once a password is set (see the
    invite-email flow in clients.py)."""
    __tablename__ = 'clients'

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(120))
    contact_email = db.Column(db.String(120))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    password_hash = db.Column(db.String(256), nullable=True)  # null until they set one via invite
    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_expires_at = db.Column(db.DateTime, nullable=True)

    campaigns = db.relationship('Campaign', backref='client', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        return self.reset_token


class Campaign(db.Model):
    """One test contract / engagement. Tasks and testers belong to a campaign."""
    __tablename__ = 'campaigns'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=False)

    name = db.Column(db.String(150), nullable=False)
    target_app_name = db.Column(db.String(150))
    platform = db.Column(db.String(50))  # Web, iOS, Android, Cross-platform

    # Draft -> Recruiting -> Active -> Review -> Paid Out -> Archived
    # Suspended and Cancelled are also end-states for export/cleanup purposes.
    status = db.Column(db.String(30), default='Draft')

    points_budget = db.Column(db.Integer, default=0)
    conversion_rate = db.Column(db.Float, default=0.01)  # NGN per point, set per client deal

    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tasks = db.relationship('Task', backref='campaign', lazy='dynamic')
    enrollments = db.relationship('Enrollment', backref='campaign', lazy='dynamic')


class Enrollment(db.Model):
    """Links a tester to a specific campaign, with campaign-scoped points."""
    __tablename__ = 'enrollments'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'), nullable=False)
    points_earned = db.Column(db.Integer, default=0)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'campaign_id', name='uq_user_campaign'),)


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    # 'Tester' or a staff role: 'Admin', 'Reviewer', 'Finance', 'Support'.
    # See permissions.py for what each staff role can actually do.
    role = db.Column(db.String(20), default='Tester')
    account_status = db.Column(db.String(30), default='Pending Email')

    verification_token = db.Column(db.String(100), unique=True, nullable=True)
    verification_otp = db.Column(db.String(6), nullable=True)
    verification_expires_at = db.Column(db.DateTime, nullable=True)

    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_expires_at = db.Column(db.DateTime, nullable=True)

    date_of_birth = db.Column(db.Date, nullable=True)

    # Redeemable balance across ALL campaigns, only touched by approved reviews
    # and redemption requests — never edited directly.
    wallet_points = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    submissions = db.relationship('Submission', backref='tester', lazy='dynamic')
    enrollments = db.relationship('Enrollment', backref='user', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='user', lazy='dynamic')
    redemptions = db.relationship('RedemptionRequest', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_otp(self):
        self.verification_otp = ''.join(secrets.choice(string.digits) for _ in range(6))
        return self.verification_otp

    def generate_token(self):
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token

    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        return self.reset_token


class Task(db.Model):
    __tablename__ = 'tasks'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'), nullable=False)

    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    base_points = db.Column(db.Integer, nullable=False)
    time_limit_minutes = db.Column(db.Integer, nullable=False, default=30)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    submissions = db.relationship('Submission', backref='task', lazy='dynamic')


class Submission(db.Model):
    __tablename__ = 'submissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)

    status = db.Column(db.String(20), default='Claimed')  # Claimed, Submitted, Approved, Rejected, Expired

    # True if this is a tester's one allowed re-attempt after a rejection
    # (claimed with a shorter time limit). Governs the task lock/retry
    # state machine in tasks.py.
    is_retry = db.Column(db.Boolean, default=False)

    tester_notes = db.Column(db.Text, nullable=True)
    admin_feedback = db.Column(db.Text, nullable=True)
    points_awarded = db.Column(db.Integer, default=0)

    claimed_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    files = db.relationship('SubmissionFile', backref='submission', lazy='dynamic',
                             cascade='all, delete-orphan')

    def is_expired(self):
        return self.status == 'Claimed' and datetime.utcnow() > self.expires_at


class SubmissionFile(db.Model):
    """One of possibly several proof screenshots attached to a submission.
    Kept on disk until the campaign ends (see campaigns.py export/purge),
    not deleted the moment a submission is reviewed."""
    __tablename__ = 'submission_files'

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)  # relative to /static
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    """Append-only ledger. wallet_points should always equal the sum of these."""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    kind = db.Column(db.String(20), nullable=False)  # Earned, Redeemed, Adjustment
    points = db.Column(db.Integer, nullable=False)   # positive or negative
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class RedemptionRequest(db.Model):
    """A tester's request to cash out points; admin marks it paid manually at first."""
    __tablename__ = 'redemption_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    points_requested = db.Column(db.Integer, nullable=False)
    cash_value = db.Column(db.Float, nullable=False)  # in Naira
    method = db.Column(db.String(50))  # Bank Transfer, PayPal, Gift Card
    payout_details = db.Column(db.String(255))
    status = db.Column(db.String(20), default='Pending')  # Pending, Paid, Denied
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)


class Notification(db.Model):
    """A message broadcast to one of several audiences. Fan-out to
    individual recipients happens immediately via NotificationRecipient
    (see notifications.py) so each person's inbox is a simple query."""
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)

    # all | all_testers | specific_tester | campaign_testers | all_clients | specific_client
    audience_type = db.Column(db.String(30), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey('campaigns.id'), nullable=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    target_client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)

    sender_staff_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_automated = db.Column(db.Boolean, default=False)
    # De-dupe key for automated sends, e.g. 'birthday:42:2026' or
    # 'deadline:917'. Left null for manually-composed notifications.
    automation_key = db.Column(db.String(100), unique=True, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    campaign = db.relationship('Campaign')
    target_user = db.relationship('User', foreign_keys=[target_user_id])
    target_client = db.relationship('Client', foreign_keys=[target_client_id])
    sender_staff = db.relationship('User', foreign_keys=[sender_staff_id])
    recipients = db.relationship('NotificationRecipient', backref='notification',
                                  lazy='dynamic', cascade='all, delete-orphan')


class NotificationRecipient(db.Model):
    """One delivered copy of a Notification, for exactly one User or one
    Client (never both)."""
    __tablename__ = 'notification_recipients'

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notifications.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    client = db.relationship('Client', foreign_keys=[client_id])


class Feedback(db.Model):
    """A message from anyone (tester or client) to the admin team."""
    __tablename__ = 'feedback'

    id = db.Column(db.Integer, primary_key=True)
    sender_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    sender_client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)
    subject = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='New')  # New, In Progress, Resolved
    admin_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    sender_user = db.relationship('User', foreign_keys=[sender_user_id])
    sender_client = db.relationship('Client', foreign_keys=[sender_client_id])


class SchedulerState(db.Model):
    """Tiny table backing the 'lazy cron' in notifications.py — tracks
    when each periodic job last actually ran, since there's no dedicated
    background worker."""
    __tablename__ = 'scheduler_state'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    last_run_at = db.Column(db.DateTime, default=datetime(2000, 1, 1))
