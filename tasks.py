import os
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    session,
    current_app,
)
from werkzeug.utils import secure_filename

from models import (
    Task,
    Submission,
    SubmissionFile,
    User,
    Campaign,
    Enrollment,
    RedemptionRequest,
    Transaction,
    Notification,
    NotificationRecipient,
    Feedback,
)
from app import db


tasks_bp = Blueprint('tasks', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILES_PER_SUBMISSION = 5


def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)

    return decorated_function


def active_tester_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = User.query.get(session['user_id'])

        if not user or user.account_status != 'Active':
            flash(
                'Your account is pending admin approval. '
                'You cannot claim missions yet.',
                'warning',
            )
            return redirect(url_for('auth.login'))

        return f(*args, **kwargs)

    return decorated_function


def task_availability(task, viewer_id=None):
    """Classifies a task's current lock state from its most recent submission.

    Returns (state, holder_user_id):

      'open'   - nobody has an exclusive claim on it right now
      'locked' - someone currently has it Claimed or Submitted
      'retry'  - a rejected tester has first refusal on one more attempt
      'done'   - a submission on it was Approved (permanently completed)
    """

    latest = (
        task.submissions
        .order_by(Submission.claimed_at.desc())
        .first()
    )

    if latest is None:
        return ('open', None)

    if latest.status in ('Claimed', 'Submitted'):
        return ('locked', latest.user_id)

    if latest.status == 'Approved':
        return ('done', latest.user_id)

    if latest.status == 'Rejected' and not latest.is_retry:
        # First rejection: the same tester gets one retry window before
        # the mission opens up to anyone else.
        return ('retry', latest.user_id)

    # Expired, or a retry attempt that was itself Rejected/Expired -> vacant.
    return ('open', None)


def task_dependency_status(task):
    """
    Returns information about whether a task's prerequisite has
    been completed.

    Returns:

        {
            'blocked': bool,
            'prerequisite': Task | None,
            'reason': str | None
        }

    A prerequisite is considered satisfied only when it has an
    Approved submission.
    """

    prerequisite = task.prerequisite_task

    if prerequisite is None:
        return {
            'blocked': False,
            'prerequisite': None,
            'reason': None,
        }

    completed_submission = (
        prerequisite.submissions
        .filter_by(status='Approved')
        .first()
    )

    if completed_submission:
        return {
            'blocked': False,
            'prerequisite': prerequisite,
            'reason': None,
        }

    return {
        'blocked': True,
        'prerequisite': prerequisite,
        'reason': (
            f'Complete "{prerequisite.title}" first.'
        ),
    }


@tasks_bp.route('/board')
@login_required
@active_tester_required
def bounty_board():
    user = User.query.get(session['user_id'])

    # Auto-expire claims whose timer ran out, instead of deleting them,
    # so there's still a record in the tester's ledger.
    expired_claims = Submission.query.filter(
        Submission.status == 'Claimed',
        Submission.expires_at < datetime.utcnow()
    ).all()

    for claim in expired_claims:
        claim.status = 'Expired'

    if expired_claims:
        db.session.commit()

    enrolled_campaign_ids = [
        e.campaign_id for e in user.enrollments
    ]

    campaigns = (
        Campaign.query.filter(
            Campaign.id.in_(enrolled_campaign_ids),
            Campaign.status == 'Active',
        ).all()
        if enrolled_campaign_ids
        else []
    )

    current_claim = Submission.query.filter_by(
        user_id=user.id,
        status='Claimed'
    ).first()

    board = []

    for campaign in campaigns:
        visible_tasks = []

        # Oldest task first.
        #
        # Hidden tasks are removed before they reach the board.
        tasks = (
            campaign.tasks
            .filter_by(is_active=True)
            .order_by(
                Task.created_at.asc(),
                Task.id.asc()
            )
            .all()
        )

        for task in tasks:
            state, holder_id = task_availability(
                task,
                user.id
            )

            dependency = task_dependency_status(task)

            # -----------------------------------------------------
            # COMPLETED TASKS
            # -----------------------------------------------------

            if state == 'done':
                continue

            # -----------------------------------------------------
            # CURRENTLY CLAIMED / SUBMITTED BY SOMEONE ELSE
            # -----------------------------------------------------

            if state == 'locked':
                continue

            # -----------------------------------------------------
            # RETRY
            # -----------------------------------------------------

            if state == 'retry':

                if holder_id == user.id:
                    retry_minutes = max(
                        5,
                        task.time_limit_minutes // 2
                    )

                    visible_tasks.append({
                        'task': task,
                        'retry': True,
                        'retry_minutes': retry_minutes,
                        'blocked': dependency['blocked'],
                        'prerequisite': dependency['prerequisite'],
                    })

                continue

            # -----------------------------------------------------
            # OPEN TASK
            # -----------------------------------------------------

            visible_tasks.append({
                'task': task,
                'retry': False,
                'blocked': dependency['blocked'],
                'prerequisite': dependency['prerequisite'],
            })

        if visible_tasks:
            board.append(
                (
                    campaign,
                    visible_tasks
                )
            )

    return render_template(
        'tasks/board.html',
        board=board,
        current_claim=current_claim,
        user=user,
    )


@tasks_bp.route('/campaigns')
@login_required
@active_tester_required
def browse_campaigns():
    user = User.query.get(session['user_id'])

    enrolled_ids = {
        e.campaign_id for e in user.enrollments
    }

    open_campaigns = Campaign.query.filter(
        Campaign.status.in_(['Recruiting', 'Active'])
    ).all()

    joinable = [
        c for c in open_campaigns
        if c.id not in enrolled_ids
    ]

    joined = [
        c for c in open_campaigns
        if c.id in enrolled_ids
    ]

    return render_template(
        'tasks/browse_campaigns.html',
        joinable=joinable,
        joined=joined,
    )


@tasks_bp.route('/campaigns/<int:campaign_id>/join', methods=['POST'])
@login_required
@active_tester_required
def join_campaign(campaign_id):
    user = User.query.get(session['user_id'])
    campaign = Campaign.query.get_or_404(campaign_id)

    if campaign.status not in ['Recruiting', 'Active']:
        flash(
            'This campaign is not open for enrollment.',
            'warning'
        )
        return redirect(url_for('tasks.browse_campaigns'))

    existing = Enrollment.query.filter_by(
        user_id=user.id,
        campaign_id=campaign.id,
    ).first()

    if not existing:
        db.session.add(
            Enrollment(
                user_id=user.id,
                campaign_id=campaign.id,
            )
        )

        db.session.commit()

        flash(
            f'Joined {campaign.name}!',
            'success'
        )

    return redirect(url_for('tasks.bounty_board'))


@tasks_bp.route('/claim/<int:task_id>', methods=['POST'])
@login_required
@active_tester_required
def claim_task(task_id):
    user = User.query.get(session['user_id'])

    existing_claim = Submission.query.filter_by(
        user_id=user.id,
        status='Claimed'
    ).first()

    if existing_claim:
        flash(
            'You already have an active mission. Finish it first.',
            'warning'
        )
        return redirect(url_for('tasks.bounty_board'))

    task = Task.query.get_or_404(task_id)

    enrollment = Enrollment.query.filter_by(
        user_id=user.id,
        campaign_id=task.campaign_id,
    ).first()

    if not enrollment:
        flash(
            'Join this campaign before claiming its missions.',
            'danger'
        )
        return redirect(url_for('tasks.bounty_board'))

    if not task.is_active or task.campaign.status != 'Active':
        flash(
            'This mission is no longer available.',
            'warning'
        )
        return redirect(url_for('tasks.bounty_board'))

    # ---------------------------------------------------------
    # DEPENDENCY ENFORCEMENT
    # ---------------------------------------------------------

    dependency = task_dependency_status(task)

    if dependency['blocked']:
        flash(
            dependency['reason'],
            'warning'
        )

        return redirect(url_for('tasks.bounty_board'))

    state, holder_id = task_availability(task, user.id)

    if state == 'locked':
        flash(
            'Someone already has this mission claimed.',
            'warning'
        )
        return redirect(url_for('tasks.bounty_board'))

    if state == 'done':
        flash(
            'This mission has already been completed.',
            'warning'
        )
        return redirect(url_for('tasks.bounty_board'))

    if state == 'retry' and holder_id != user.id:
        flash(
            'This mission is in a retry window reserved for another tester.',
            'warning'
        )
        return redirect(url_for('tasks.bounty_board'))

    is_retry = state == 'retry'

    minutes = (
        max(5, task.time_limit_minutes // 2)
        if is_retry
        else task.time_limit_minutes
    )

    expiration_time = (
        datetime.utcnow()
        + timedelta(minutes=minutes)
    )

    new_claim = Submission(
        user_id=user.id,
        task_id=task.id,
        status='Claimed',
        expires_at=expiration_time,
        is_retry=is_retry,
    )

    db.session.add(new_claim)
    db.session.commit()

    note = (
        'Retry claimed!'
        if is_retry
        else 'Mission claimed!'
    )

    flash(
        f'{note} {minutes} minutes on the clock.',
        'success'
    )

    return redirect(
        url_for(
            'tasks.submit_proof',
            submission_id=new_claim.id,
        )
    )


@tasks_bp.route('/submit/<int:submission_id>', methods=['GET', 'POST'])
@login_required
def submit_proof(submission_id):
    submission = Submission.query.get_or_404(submission_id)
    user = User.query.get(session['user_id'])

    if submission.user_id != user.id:
        flash(
            'Unauthorized access.',
            'danger'
        )
        return redirect(url_for('tasks.bounty_board'))

    if submission.status != 'Claimed':
        flash(
            'This mission is no longer open for submission.',
            'warning'
        )
        return redirect(url_for('tasks.bounty_board'))

    if submission.is_expired():
        submission.status = 'Expired'
        db.session.commit()

        flash(
            'Time ran out! Your claim expired.',
            'danger'
        )

        return redirect(url_for('tasks.bounty_board'))

    if request.method == 'POST':
        files = [
            f
            for f in request.files.getlist('screenshots')
            if f and f.filename
        ]

        if not files:
            flash(
                'Please choose at least one screenshot.',
                'danger'
            )
            return redirect(request.url)

        if len(files) > MAX_FILES_PER_SUBMISSION:
            flash(
                f'You can attach up to '
                f'{MAX_FILES_PER_SUBMISSION} screenshots.',
                'danger'
            )
            return redirect(request.url)

        for f in files:
            if not allowed_file(f.filename):
                flash(
                    f'"{f.filename}" is not a supported image type '
                    f'(PNG, JPG, GIF, WEBP only).',
                    'danger'
                )
                return redirect(request.url)

        upload_dir = os.path.join(
            current_app.root_path,
            'static',
            'uploads'
        )

        os.makedirs(
            upload_dir,
            exist_ok=True
        )

        for i, f in enumerate(files):
            filename = secure_filename(
                f"user_{user.id}_sub_{submission.id}_{i}_{f.filename}"
            )

            f.save(
                os.path.join(
                    upload_dir,
                    filename
                )
            )

            db.session.add(
                SubmissionFile(
                    submission_id=submission.id,
                    file_path=f"uploads/{filename}",
                )
            )

        submission.tester_notes = request.form.get(
            'notes',
            ''
        ).strip()

        submission.status = 'Submitted'
        submission.submitted_at = datetime.utcnow()

        db.session.commit()

        flash(
            'Proof submitted! Awaiting admin review.',
            'success'
        )

        return redirect(url_for('tasks.bounty_board'))

    return render_template(
        'tasks/submit_proof.html',
        submission=submission,
        max_files=MAX_FILES_PER_SUBMISSION,
    )


@tasks_bp.route('/ledger')
@login_required
def user_ledger():
    user = User.query.get(session['user_id'])

    history = (
        Submission.query
        .filter_by(user_id=user.id)
        .order_by(Submission.claimed_at.desc())
        .all()
    )

    return render_template(
        'tasks/ledger.html',
        history=history,
        user=user,
    )


@tasks_bp.route('/leaderboard')
@login_required
def leaderboard():
    user = User.query.get(session['user_id'])

    campaign_id = request.args.get(
        'campaign_id',
        type=int
    )

    enrolled_campaigns = [
        e.campaign for e in user.enrollments
    ]

    rows = []
    selected_campaign = None

    target_id = (
        campaign_id
        or (
            enrolled_campaigns[0].id
            if enrolled_campaigns
            else None
        )
    )

    if target_id:
        selected_campaign = Campaign.query.get_or_404(
            target_id
        )

        enrollments = (
            Enrollment.query
            .filter_by(campaign_id=target_id)
            .order_by(Enrollment.points_earned.desc())
            .all()
        )

        rows = [
            (e.user, e.points_earned)
            for e in enrollments
        ]

    return render_template(
        'tasks/leaderboard.html',
        rows=rows,
        enrolled_campaigns=enrolled_campaigns,
        selected_campaign=selected_campaign,
        user=user,
    )


@tasks_bp.route('/redeem', methods=['GET', 'POST'])
@login_required
def redeem():
    user = User.query.get(session['user_id'])

    point_value = current_app.config.get(
        'POINT_VALUE_NGN',
        5
    )

    if request.method == 'POST':
        points_requested = request.form.get(
            'points_requested',
            type=int
        )

        method = request.form.get(
            'method',
            ''
        ).strip()

        payout_details = request.form.get(
            'payout_details',
            ''
        ).strip()

        if not points_requested or points_requested <= 0:
            flash(
                'Enter a valid number of points.',
                'danger'
            )
            return redirect(url_for('tasks.redeem'))

        if points_requested > user.wallet_points:
            flash(
                "You don't have that many points to redeem.",
                'danger'
            )
            return redirect(url_for('tasks.redeem'))

        if not method or not payout_details:
            flash(
                'Choose a payout method and provide your details.',
                'danger'
            )
            return redirect(url_for('tasks.redeem'))

        cash_value = round(
            points_requested * point_value,
            2
        )

        user.wallet_points -= points_requested

        redemption = RedemptionRequest(
            user_id=user.id,
            points_requested=points_requested,
            cash_value=cash_value,
            method=method,
            payout_details=payout_details,
            status='Pending',
        )

        db.session.add(redemption)

        db.session.add(
            Transaction(
                user_id=user.id,
                kind='Redeemed',
                points=-points_requested,
                note=f'Redemption request ({method})',
            )
        )

        db.session.commit()

        flash(
            f'Redemption requested for '
            f'₦{cash_value:,.2f}. '
            f'An admin will process it shortly.',
            'success'
        )

        return redirect(url_for('tasks.redeem'))

    history = (
        RedemptionRequest.query
        .filter_by(user_id=user.id)
        .order_by(RedemptionRequest.requested_at.desc())
        .all()
    )

    return render_template(
        'tasks/redeem.html',
        user=user,
        history=history,
        point_value=point_value,
    )


@tasks_bp.route('/notifications')
@login_required
def notifications():
    user = User.query.get(session['user_id'])

    items = (
        NotificationRecipient.query
        .filter_by(user_id=user.id)
        .join(Notification)
        .order_by(Notification.created_at.desc())
        .all()
    )

    unread_ids = [
        r.id
        for r in items
        if not r.read_at
    ]

    if unread_ids:
        NotificationRecipient.query.filter(
            NotificationRecipient.id.in_(unread_ids)
        ).update(
            {'read_at': datetime.utcnow()},
            synchronize_session=False
        )

        db.session.commit()

    return render_template(
        'tasks/notifications.html',
        items=items@tasks_bp.route('/feedback', methods=['GET', 'POST'])
@login_required
def feedback():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        subject = request.form.get(
            'subject',
            ''
        ).strip()

        message = request.form.get(
            'message',
            ''
        ).strip()

        if not subject or not message:
            flash(
                'Subject and message are required.',
                'danger'
            )
        else:
            db.session.add(
                Feedback(
                    sender_user_id=user.id,
                    subject=subject,
                    message=message,
                )
            )

            db.session.commit()

            flash(
                'Sent — the Waypoint team will get back to you.',
                'success'
            )

        return redirect(
            url_for('tasks.feedback')
        )

    history = (
        Feedback.query
        .filter_by(sender_user_id=user.id)
        .order_by(Feedback.created_at.desc())
        .all()
    )

    return render_template(
        'tasks/feedback.html',
        history=history
    )


@tasks_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        dob_raw = request.form.get(
            'date_of_birth',
            ''
        ).strip()

        if dob_raw:
            try:
                user.date_of_birth = datetime.strptime(
                    dob_raw,
                    '%Y-%m-%d'
                ).date()

                db.session.commit()

                flash(
                    'Profile updated.',
                    'success'
                )

            except ValueError:
                flash(
                    "That date of birth doesn't look right.",
                    'danger'
                )

        return redirect(
            url_for('tasks.profile')
        )

    return render_template(
        'tasks/profile.html',
        user=user
    )
    )


 
