import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_mail import Message
from models import (User, Task, Submission, Campaign, Enrollment, Transaction, RedemptionRequest,
                     SubmissionFile, Client, Notification, Feedback)
from app import db, mail
from permissions import staff_required, permission_required, STAFF_ROLES
from notifications import create_notification
from promo import load_promo_config, save_promo_config, is_promo_live

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

STAFF_CREATABLE_ROLES = ['Admin', 'Reviewer', 'Finance', 'Support']


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@staff_required
def dashboard():
    pending_users_count = User.query.filter_by(account_status='Pending Approval').count()
    pending_reviews_count = Submission.query.filter_by(status='Submitted').count()
    active_campaigns_count = Campaign.query.filter_by(status='Active').count()
    recruiting_campaigns_count = Campaign.query.filter_by(status='Recruiting').count()
    pending_payouts_count = RedemptionRequest.query.filter_by(status='Pending').count()
    open_feedback_count = Feedback.query.filter(Feedback.status != 'Resolved').count()

    return render_template(
        'admin/dashboard.html',
        pending_users=pending_users_count,
        pending_reviews=pending_reviews_count,
        active_campaigns=active_campaigns_count,
        recruiting_campaigns=recruiting_campaigns_count,
        pending_payouts=pending_payouts_count,
        open_feedback=open_feedback_count,
    )


# ==========================================
# ACCESS CONTROL
# ==========================================
@admin_bp.route('/pending-users')
@permission_required('access.manage')
def pending_users():
    pending = User.query.filter_by(account_status='Pending Approval').all()
    stuck_email = User.query.filter_by(account_status='Pending Email').all()
    return render_template('admin/pending_users.html', pending=pending, stuck_email=stuck_email)


@admin_bp.route('/approve/<int:user_id>', methods=['POST'])
@permission_required('access.manage')
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.account_status == 'Pending Approval':
        user.account_status = 'Active'
        db.session.commit()
        flash(f'User @{user.username} has been approved and is now Active!', 'success')
    return redirect(url_for('admin.pending_users'))


@admin_bp.route('/reject/<int:user_id>', methods=['POST'])
@permission_required('access.manage')
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash(f'User @{user.username} was rejected and removed.', 'warning')
    return redirect(url_for('admin.pending_users'))


@admin_bp.route('/cleanup-stale-accounts', methods=['POST'])
@permission_required('access.manage')
def cleanup_stale():
    threshold = datetime.utcnow() - timedelta(hours=24)
    stale_users = User.query.filter(User.account_status == 'Pending Email', User.created_at < threshold).all()
    count = len(stale_users)
    for u in stale_users:
        db.session.delete(u)
    db.session.commit()
    flash(f'Cleaned up {count} stale unverified accounts.', 'success')
    return redirect(url_for('admin.pending_users'))


# ==========================================
# REVIEW QUEUE
# ==========================================
@admin_bp.route('/review-queue')
@permission_required('reviews.manage')
def review_queue():
    pending_reviews = Submission.query.filter_by(status='Submitted').all()
    return render_template('admin/review_queue.html', submissions=pending_reviews)


@admin_bp.route('/process-review/<int:sub_id>', methods=['POST'])
@permission_required('reviews.manage')
def process_review(sub_id):
    sub = Submission.query.get_or_404(sub_id)
    action = request.form.get('action')
    feedback = request.form.get('feedback', '').strip()

    user = sub.tester
    task = sub.task
    campaign = task.campaign

    if action == 'approve':
        sub.status = 'Approved'
        sub.points_awarded = task.base_points
        task.is_active = False  # completed for good — auto-hide

        enrollment = Enrollment.query.filter_by(user_id=user.id, campaign_id=campaign.id).first()
        if not enrollment:
            enrollment = Enrollment(user_id=user.id, campaign_id=campaign.id)
            db.session.add(enrollment)
        enrollment.points_earned += task.base_points

        user.wallet_points += task.base_points
        db.session.add(Transaction(
            user_id=user.id, kind='Earned', points=task.base_points,
            note=f'{task.title} ({campaign.name})',
        ))
        flash(f'Approved! {task.base_points} PTS awarded to @{user.username}.', 'success')
    elif action == 'reject':
        sub.status = 'Rejected'
        if sub.is_retry:
            flash(f'Rejected. @{user.username} used their retry — mission is open to anyone now.', 'warning')
        else:
            flash(f'Rejected. @{user.username} gets one retry with a shorter time limit.', 'warning')

    sub.admin_feedback = feedback
    sub.reviewed_at = datetime.utcnow()
    # Screenshots stay — purged in bulk from campaigns.py once the whole
    # campaign has ended, after an export.
    db.session.commit()
    return redirect(url_for('admin.review_queue'))


@admin_bp.route('/master-ledger')
@permission_required('payouts.manage', 'reviews.manage')
def master_ledger():
    approved_submissions = Submission.query.filter_by(status='Approved').order_by(Submission.reviewed_at.desc()).all()
    return render_template('admin/master_ledger.html', submissions=approved_submissions)


# ==========================================
# PAYOUTS
# ==========================================
@admin_bp.route('/payouts')
@permission_required('payouts.manage')
def payouts_queue():
    pending = RedemptionRequest.query.filter_by(status='Pending').order_by(RedemptionRequest.requested_at).all()
    return render_template('admin/payouts_queue.html', payouts=pending)


@admin_bp.route('/payouts/<int:payout_id>/resolve', methods=['POST'])
@permission_required('payouts.manage')
def resolve_payout(payout_id):
    payout = RedemptionRequest.query.get_or_404(payout_id)
    action = request.form.get('action')

    if payout.status != 'Pending':
        flash('This request was already resolved.', 'warning')
        return redirect(url_for('admin.payouts_queue'))

    if action == 'paid':
        payout.status = 'Paid'
        flash(f'Marked ₦{payout.cash_value:,.2f} paid to @{payout.user.username}.', 'success')
    elif action == 'denied':
        payout.status = 'Denied'
        payout.user.wallet_points += payout.points_requested
        db.session.add(Transaction(
            user_id=payout.user.id, kind='Adjustment', points=payout.points_requested,
            note=f'Redemption request #{payout.id} denied — refunded',
        ))
        flash(f'Denied and refunded {payout.points_requested} PTS to @{payout.user.username}.', 'warning')

    payout.resolved_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for('admin.payouts_queue'))


# ==========================================
# STAFF — invited via the same reset-password link as "forgot password",
# just used here to let them set their first password.
# ==========================================
@admin_bp.route('/staff')
@permission_required('staff.manage')
def staff_list():
    staff = User.query.filter(User.role.in_(STAFF_CREATABLE_ROLES)).order_by(User.created_at.desc()).all()
    return render_template('admin/staff_list.html', staff=staff)


@admin_bp.route('/staff/new', methods=['GET', 'POST'])
@permission_required('staff.manage')
def new_staff():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        role = request.form.get('role', '')

        if role not in STAFF_CREATABLE_ROLES:
            flash('Choose a valid role.', 'danger')
            return redirect(url_for('admin.new_staff'))
        if User.query.filter_by(username=username).first():
            flash('That username is already taken.', 'danger')
            return redirect(url_for('admin.new_staff'))
        if User.query.filter_by(email=email).first():
            flash('That email is already registered.', 'danger')
            return redirect(url_for('admin.new_staff'))

        staff_member = User(username=username, email=email, role=role, account_status='Active')
        staff_member.set_password(secrets.token_urlsafe(24))  # placeholder — replaced via invite link
        token = staff_member.generate_reset_token()
        staff_member.reset_expires_at = datetime.utcnow() + timedelta(hours=48)
        db.session.add(staff_member)
        db.session.commit()

        invite_link = url_for('auth.reset_password', token=token, _external=True)
        body = (
            f"Hello {username},\n\nYou've been added to Waypoint as {role} staff.\n"
            f"Set your password here (link expires in 48 hours):\n{invite_link}"
        )
        try:
            mail.send(Message(subject="You've been added to Waypoint", recipients=[email], body=body))
            flash(f'Invited {username} as {role}.', 'success')
        except Exception as e:
            flash(f'Account created, but the invite email failed to send. Share this link directly: {invite_link}', 'warning')
            print(f"Mail Error: {e}")

        return redirect(url_for('admin.staff_list'))

    return render_template('admin/staff_new.html', roles=STAFF_CREATABLE_ROLES)


# ==========================================
# NOTIFICATIONS
# ==========================================
@admin_bp.route('/notifications')
@permission_required('support.manage')
def notifications_list():
    sent = Notification.query.order_by(Notification.created_at.desc()).limit(100).all()
    return render_template('admin/notifications_list.html', notifications=sent)


@admin_bp.route('/notifications/new', methods=['GET', 'POST'])
@permission_required('support.manage')
def new_notification():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        body = request.form.get('body', '').strip()
        audience_type = request.form.get('audience_type')
        campaign_id = request.form.get('campaign_id', type=int)
        target_user_id = request.form.get('target_user_id', type=int)
        target_client_id = request.form.get('target_client_id', type=int)

        if not title or not body or not audience_type:
            flash('Title, message, and audience are required.', 'danger')
            return redirect(url_for('admin.new_notification'))

        create_notification(
            title=title, body=body, audience_type=audience_type,
            campaign_id=campaign_id if audience_type == 'campaign_testers' else None,
            target_user_id=target_user_id if audience_type == 'specific_tester' else None,
            target_client_id=target_client_id if audience_type == 'specific_client' else None,
            sender_staff_id=session.get('user_id'),
        )
        flash('Notification sent.', 'success')
        return redirect(url_for('admin.notifications_list'))

    campaigns = Campaign.query.filter_by(status='Active').order_by(Campaign.name).all()
    testers = User.query.filter_by(role='Tester').order_by(User.username).all()
    clients = Client.query.order_by(Client.company_name).all()
    return render_template('admin/notifications_new.html', campaigns=campaigns, testers=testers, clients=clients)


# ==========================================
# FEEDBACK INBOX
# ==========================================
@admin_bp.route('/feedback')
@permission_required('support.manage')
def feedback_list():
    items = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return render_template('admin/feedback_list.html', items=items)


@admin_bp.route('/feedback/<int:feedback_id>/respond', methods=['POST'])
@permission_required('support.manage')
def feedback_respond(feedback_id):
    item = Feedback.query.get_or_404(feedback_id)
    response = request.form.get('admin_response', '').strip()
    new_status = request.form.get('status', 'Resolved')

    item.admin_response = response
    item.status = new_status
    item.resolved_at = datetime.utcnow() if new_status == 'Resolved' else None
    db.session.commit()

    recipient_email = None
    if item.sender_user:
        recipient_email = item.sender_user.email
    elif item.sender_client:
        recipient_email = item.sender_client.contact_email

    if recipient_email and response:
        try:
            mail.send(Message(subject=f'Re: {item.subject}', recipients=[recipient_email],
                               body=f"Hi,\n\n{response}\n\n— Waypoint Support"))
        except Exception as e:
            print(f"Mail Error: {e}")

    flash('Response saved.', 'success')
    return redirect(url_for('admin.feedback_list'))


# ==========================================
# PROMO SEASON — file-based toggle, no migration involved. Gated to
# campaigns.manage, which in the current 4-role setup means Admin only:
# this is a site-wide business decision, not something any staff role
# should be able to flip casually.
# ==========================================
@admin_bp.route('/promo')
@permission_required('campaigns.manage')
def promo_settings():
    config = load_promo_config()
    return render_template('admin/promo.html', config=config, is_live=is_promo_live())


@admin_bp.route('/promo/toggle', methods=['POST'])
@permission_required('campaigns.manage')
def promo_toggle():
    config = load_promo_config()
    config['active'] = not config.get('active', False)
    save_promo_config(config)
    flash(f"Promo Season is now {'ON' if config['active'] else 'OFF'}.", 'success')
    return redirect(url_for('admin.promo_settings'))


@admin_bp.route('/promo/update', methods=['POST'])
@permission_required('campaigns.manage')
def promo_update():
    config = load_promo_config()
    config['deadline'] = request.form.get('deadline', '').strip() or None
    config['points_pool'] = request.form.get('points_pool', type=int) or 0
    config['sponsor'] = request.form.get('sponsor', '').strip()
    save_promo_config(config)
    flash('Promo details updated.', 'success')
    return redirect(url_for('admin.promo_settings'))
