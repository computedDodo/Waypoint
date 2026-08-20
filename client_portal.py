from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_mail import Message
from models import Client, Campaign, Task, Notification, NotificationRecipient, Feedback
from app import db, mail
from exports import build_campaign_export

client_portal_bp = Blueprint('client_portal', __name__, url_prefix='/client')

RESET_TOKEN_HOURS = 24


def client_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'client_id' not in session:
            flash('Please log in to view your dashboard.', 'warning')
            return redirect(url_for('client_portal.login'))
        return f(*args, **kwargs)
    return decorated_function


@client_portal_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        client = Client.query.filter_by(contact_email=email).first()

        if client and client.check_password(password):
            session['client_id'] = client.id
            return redirect(url_for('client_portal.dashboard'))
        flash('Invalid email or password.', 'danger')

    return render_template('client/login.html')


@client_portal_bp.route('/logout')
def logout():
    session.pop('client_id', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('client_portal.login'))


@client_portal_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        client = Client.query.filter_by(contact_email=email).first()

        if client:
            token = client.generate_reset_token()
            client.reset_expires_at = datetime.utcnow() + timedelta(hours=RESET_TOKEN_HOURS)
            db.session.commit()

            reset_link = url_for('client_portal.reset_password', token=token, _external=True)
            body = (
                f"Hello {client.contact_name or client.company_name},\n\n"
                f"Click below to set a new password. It expires in {RESET_TOKEN_HOURS} hours:\n{reset_link}"
            )
            try:
                mail.send(Message(subject="Reset your Waypoint portal password", recipients=[email], body=body))
            except Exception as e:
                print(f"Mail Error: {e}")

        flash('If that email is on file, a reset link has been sent.', 'success')
        return redirect(url_for('client_portal.login'))

    return render_template('client/forgot_password.html')


@client_portal_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    client = Client.query.filter_by(reset_token=token).first()

    if not client or not client.reset_expires_at or datetime.utcnow() > client.reset_expires_at:
        flash('That link is invalid or has expired. Request a new one.', 'danger')
        return redirect(url_for('client_portal.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return redirect(url_for('client_portal.reset_password', token=token))
        if password != confirm:
            flash("Passwords don't match.", 'danger')
            return redirect(url_for('client_portal.reset_password', token=token))

        client.set_password(password)
        client.reset_token = None
        client.reset_expires_at = None
        db.session.commit()

        flash('Password set. Sign in below.', 'success')
        return redirect(url_for('client_portal.login'))

    return render_template('client/reset_password.html', token=token)


@client_portal_bp.route('/dashboard')
@client_required
def dashboard():
    client = Client.query.get_or_404(session['client_id'])
    campaigns = client.campaigns.order_by(Campaign.created_at.desc()).all()

    active_count = sum(1 for c in campaigns if c.status == 'Active')
    total_testers = sum(c.enrollments.count() for c in campaigns)
    total_approved = sum(
        Task.query.filter_by(campaign_id=c.id).count() for c in campaigns
    )

    return render_template(
        'client/dashboard.html',
        client=client,
        campaigns=campaigns,
        active_count=active_count,
        total_testers=total_testers,
        total_missions=total_approved,
    )


@client_portal_bp.route('/campaigns/<int:campaign_id>')
@client_required
def campaign_detail(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    if campaign.client_id != session['client_id']:
        flash('That campaign is not on your account.', 'danger')
        return redirect(url_for('client_portal.dashboard'))

    tasks = campaign.tasks.order_by(Task.created_at.desc()).all()
    return render_template('client/campaign_detail.html', campaign=campaign, tasks=tasks)


@client_portal_bp.route('/campaigns/<int:campaign_id>/export')
@client_required
def export_campaign(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    if campaign.client_id != session['client_id']:
        flash('That campaign is not on your account.', 'danger')
        return redirect(url_for('client_portal.dashboard'))
    return build_campaign_export(campaign)


@client_portal_bp.route('/notifications')
@client_required
def notifications():
    items = (NotificationRecipient.query
             .filter_by(client_id=session['client_id'])
             .join(Notification)
             .order_by(Notification.created_at.desc())
             .all())
    unread_ids = [r.id for r in items if not r.read_at]
    if unread_ids:
        NotificationRecipient.query.filter(NotificationRecipient.id.in_(unread_ids)).update(
            {'read_at': datetime.utcnow()}, synchronize_session=False
        )
        db.session.commit()
    return render_template('client/notifications.html', items=items)


@client_portal_bp.route('/feedback', methods=['GET', 'POST'])
@client_required
def feedback():
    client = Client.query.get_or_404(session['client_id'])

    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        if not subject or not message:
            flash('Subject and message are required.', 'danger')
        else:
            db.session.add(Feedback(sender_client_id=client.id, subject=subject, message=message))
            db.session.commit()
            flash('Sent — the Waypoint team will get back to you.', 'success')
        return redirect(url_for('client_portal.feedback'))

    history = Feedback.query.filter_by(sender_client_id=client.id).order_by(Feedback.created_at.desc()).all()
    return render_template('client/feedback.html', history=history)
