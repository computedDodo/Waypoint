import os
from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from models import Campaign, Client, Task, Submission
from permissions import permission_required
from notifications import create_notification
from exports import build_campaign_export
from app import db

campaigns_bp = Blueprint('campaigns', __name__, url_prefix='/admin/campaigns')

STATUSES = ['Draft', 'Recruiting', 'Active', 'Review', 'Paid Out', 'Suspended', 'Cancelled', 'Archived']
ENDED_STATUSES = {'Paid Out', 'Suspended', 'Cancelled', 'Archived'}


@campaigns_bp.route('/')
@permission_required('campaigns.manage')
def list_campaigns():
    status_filter = request.args.get('status')
    query = Campaign.query
    if status_filter and status_filter in STATUSES:
        query = query.filter_by(status=status_filter)
    campaigns = query.order_by(Campaign.created_at.desc()).all()
    return render_template('admin/campaigns_list.html', campaigns=campaigns, statuses=STATUSES, active_status=status_filter)


@campaigns_bp.route('/new', methods=['GET', 'POST'])
@permission_required('campaigns.manage')
def new_campaign():
    preselected_client_id = request.args.get('client_id', type=int)

    if request.method == 'POST':
        client_id = request.form.get('client_id', type=int)
        name = request.form.get('name', '').strip()
        target_app_name = request.form.get('target_app_name', '').strip()
        platform = request.form.get('platform', '').strip()
        points_budget = request.form.get('points_budget', type=int) or 0
        conversion_rate = request.form.get('conversion_rate', type=float) or 0.01

        if not client_id or not name:
            flash('A client and campaign name are required.', 'danger')
            return redirect(url_for('campaigns.new_campaign', client_id=client_id))

        campaign = Campaign(
            client_id=client_id,
            name=name,
            target_app_name=target_app_name,
            platform=platform,
            points_budget=points_budget,
            conversion_rate=conversion_rate,
            status='Draft',
        )
        db.session.add(campaign)
        db.session.commit()
        flash(f'Campaign "{name}" created as a Draft.', 'success')
        return redirect(url_for('campaigns.view_campaign', campaign_id=campaign.id))

    clients = Client.query.order_by(Client.company_name).all()
    return render_template('admin/campaign_new.html', clients=clients, preselected_client_id=preselected_client_id)


@campaigns_bp.route('/<int:campaign_id>')
@permission_required('campaigns.manage')
def view_campaign(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    tasks = campaign.tasks.order_by(Task.created_at.asc(), Task.id.asc()).all()
    enrolled_count = campaign.enrollments.count()
    proof_file_count = sum(sub.files.count() for sub in
                            Submission.query.join(Task).filter(Task.campaign_id == campaign.id).all())
    return render_template(
        'admin/campaign_detail.html',
        campaign=campaign,
        tasks=tasks,
        enrolled_count=enrolled_count,
        statuses=STATUSES,
        ended_statuses=ENDED_STATUSES,
        proof_file_count=proof_file_count,
    )


@campaigns_bp.route('/<int:campaign_id>/status', methods=['POST'])
@permission_required('campaigns.manage')
def update_status(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    new_status = request.form.get('status')
    previous_status = campaign.status

    if new_status in STATUSES:
        campaign.status = new_status
        if new_status == 'Active' and not campaign.start_date:
            campaign.start_date = datetime.utcnow()
        if new_status in ENDED_STATUSES and not campaign.end_date:
            campaign.end_date = datetime.utcnow()
        db.session.commit()
        flash(f'Campaign moved to "{new_status}".', 'success')

        # First time this campaign opens for enrollment, let every tester know.
        if new_status == 'Recruiting' and previous_status != 'Recruiting':
            create_notification(
                title=f'New campaign open: {campaign.name}',
                body=f'{campaign.client.company_name} just opened "{campaign.name}" for testers. Come take a look!',
                audience_type='all_testers',
                is_automated=True,
                automation_key=f'campaign-open:{campaign.id}',
            )

    return redirect(url_for('campaigns.view_campaign', campaign_id=campaign.id))


# ---------- tasks now live under a campaign ----------
@campaigns_bp.route('/<int:campaign_id>/tasks/new', methods=['POST'])
@permission_required('campaigns.manage')
def new_task(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)

    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()

    base_points = request.form.get(
        'base_points',
        type=int
    )

    time_limit = request.form.get(
        'time_limit_minutes',
        type=int
    )

    prerequisite_task_id = request.form.get(
        'prerequisite_task_id',
        type=int
    )

    if not title or not description or not base_points or not time_limit:
        flash(
            'All mission fields are required.',
            'danger'
        )
    
    prerequisite_task = None

    if prerequisite_task_id:

        prerequisite_task = Task.query.filter_by(
            id=prerequisite_task_id,
            campaign_id=campaign.id
        ).first()

        if not prerequisite_task:

            flash(
                'Invalid prerequisite mission selected.',
                'danger'
            )

            return redirect(url_for('campaigns.view_campaign', campaign_id=campaign.id))

    if base_points < 1:
        flash(
            'Base points must be at least 1.',
            'danger'
        )

        return redirect(
            url_for(
                'campaigns.view_campaign',
                campaign_id=campaign.id
            )
        )

    if time_limit < 1:
        flash(
            'Time limit must be at least 1 minute.',
            'danger'
        )

        return redirect(
            url_for(
                'campaigns.view_campaign',
                campaign_id=campaign.id
            )
        )

    # ---------------------------------------------------------
    # VALIDATE PREREQUISITE
    # ---------------------------------------------------------

    prerequisite_task = None

    if prerequisite_task_id:
        prerequisite_task = Task.query.filter_by(
            id=prerequisite_task_id,
            campaign_id=campaign.id
        ).first()

        if not prerequisite_task:
            flash(
                'The selected prerequisite is not part of this campaign.',
                'danger'
            )

            return redirect(
                url_for(
                    'campaigns.view_campaign',
                    campaign_id=campaign.id
                )
            )

    task = Task(
        campaign_id=campaign.id,
        title=title,
        description=description,
        base_points=base_points,
        time_limit_minutes=time_limit,
        prerequisite_task_id=(
            prerequisite_task.id
            if prerequisite_task
            else None
        ),
    )

    db.session.add(task)
    db.session.commit()

    flash(
        f'Mission "{title}" added to {campaign.name}.',
        'success'
    )

    if campaign.status == 'Active':
        dependency_text = ''

        if prerequisite_task:
            dependency_text = (
                f' Complete "{prerequisite_task.title}" first.'
            )

        create_notification(
            title=f'New mission on {campaign.name}',
            body=(
                f'"{title}" just went live — '
                f'{base_points} PTS, '
                f'{time_limit} min limit.'
                f'{dependency_text}'
            ),
            audience_type='campaign_testers',
            campaign_id=campaign.id,
            is_automated=True,
            automation_key=f'new-task:{task.id}',
        )

    return redirect(
        url_for(
            'campaigns.view_campaign',
            campaign_id=campaign.id
        )
    )

@campaigns_bp.route('/tasks/<int:task_id>/toggle', methods=['POST'])
@permission_required('campaigns.manage')
def toggle_task(task_id):
    task = Task.query.get_or_404(task_id)
    task.is_active = not task.is_active
    db.session.commit()
    status = "published to the board" if task.is_active else "hidden from testers"
    flash(f'Mission "{task.title}" is now {status}.', 'success')
    return redirect(url_for('campaigns.view_campaign', campaign_id=task.campaign_id))


# ---------- export & purge, for wrapping up an ended campaign ----------
@campaigns_bp.route('/<int:campaign_id>/export')
@permission_required('campaigns.manage')
def export_campaign(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)
    return build_campaign_export(campaign)


@campaigns_bp.route('/<int:campaign_id>/purge-proofs', methods=['POST'])
@permission_required('campaigns.manage')
def purge_proofs(campaign_id):
    campaign = Campaign.query.get_or_404(campaign_id)

    if campaign.status not in ENDED_STATUSES:
        flash('Only ended campaigns (Paid Out, Suspended, Cancelled, Archived) can be purged.', 'danger')
        return redirect(url_for('campaigns.view_campaign', campaign_id=campaign.id))

    submissions = Submission.query.join(Task).filter(Task.campaign_id == campaign.id).all()
    removed = 0
    for sub in submissions:
        for f in list(sub.files):
            abs_path = os.path.join(current_app.root_path, 'static', f.file_path)
            if os.path.exists(abs_path):
                os.remove(abs_path)
                removed += 1
            db.session.delete(f)
    db.session.commit()
    flash(f'Purged {removed} screenshot file(s) for {campaign.name}. Points and history stay intact.', 'success')
    return redirect(url_for('campaigns.view_campaign', campaign_id=campaign.id))
            
