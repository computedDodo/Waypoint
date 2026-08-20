from datetime import datetime, timedelta
from models import (Notification, NotificationRecipient, User, Client,
                     Enrollment, Submission, SchedulerState)
from app import db

CHECK_INTERVAL = timedelta(hours=1)
DEADLINE_WARNING_WINDOW = timedelta(minutes=30)


def create_notification(title, body, audience_type, campaign_id=None,
                         target_user_id=None, target_client_id=None,
                         is_automated=False, automation_key=None, sender_staff_id=None):
    """Creates a Notification and immediately fans it out to
    NotificationRecipient rows. Returns None (and does nothing) if
    automation_key is given and a notification with that key already
    exists, so automated jobs are safe to re-run."""
    if automation_key:
        if Notification.query.filter_by(automation_key=automation_key).first():
            return None

    notif = Notification(
        title=title, body=body, audience_type=audience_type, campaign_id=campaign_id,
        target_user_id=target_user_id, target_client_id=target_client_id,
        is_automated=is_automated, automation_key=automation_key, sender_staff_id=sender_staff_id,
    )
    db.session.add(notif)
    db.session.flush()  # assigns notif.id without a separate round trip

    if audience_type == 'all':
        for u in User.query.filter_by(role='Tester').all():
            db.session.add(NotificationRecipient(notification_id=notif.id, user_id=u.id))
        for c in Client.query.all():
            db.session.add(NotificationRecipient(notification_id=notif.id, client_id=c.id))
    elif audience_type == 'all_testers':
        for u in User.query.filter_by(role='Tester').all():
            db.session.add(NotificationRecipient(notification_id=notif.id, user_id=u.id))
    elif audience_type == 'specific_tester' and target_user_id:
        db.session.add(NotificationRecipient(notification_id=notif.id, user_id=target_user_id))
    elif audience_type == 'campaign_testers' and campaign_id:
        for e in Enrollment.query.filter_by(campaign_id=campaign_id).all():
            db.session.add(NotificationRecipient(notification_id=notif.id, user_id=e.user_id))
    elif audience_type == 'all_clients':
        for c in Client.query.all():
            db.session.add(NotificationRecipient(notification_id=notif.id, client_id=c.id))
    elif audience_type == 'specific_client' and target_client_id:
        db.session.add(NotificationRecipient(notification_id=notif.id, client_id=target_client_id))

    db.session.commit()
    return notif


def run_due_automations():
    """'Lazy cron' — call this opportunistically (e.g. once per request).
    It's cheap: one row read, and it only does real work once per
    CHECK_INTERVAL. No background worker or paid scheduled-task tier
    required. If you later add a real PythonAnywhere scheduled task, it
    can call this same function directly instead."""
    state = SchedulerState.query.filter_by(key='daily_checks').first()
    if not state:
        state = SchedulerState(key='daily_checks', last_run_at=datetime(2000, 1, 1))
        db.session.add(state)
        db.session.commit()

    if datetime.utcnow() - state.last_run_at < CHECK_INTERVAL:
        return

    _check_birthdays()
    _check_upcoming_deadlines()

    state.last_run_at = datetime.utcnow()
    db.session.commit()


def _check_birthdays():
    today = datetime.utcnow().date()
    users = User.query.filter(User.date_of_birth.isnot(None), User.role == 'Tester').all()
    for u in users:
        if u.date_of_birth.month == today.month and u.date_of_birth.day == today.day:
            create_notification(
                title='Happy Birthday! 🎉',
                body=f'The whole Waypoint team wishes you a great one, {u.username}!',
                audience_type='specific_tester',
                target_user_id=u.id,
                is_automated=True,
                automation_key=f'birthday:{u.id}:{today.year}',
            )


def _check_upcoming_deadlines():
    soon = datetime.utcnow() + DEADLINE_WARNING_WINDOW
    claims = Submission.query.filter(
        Submission.status == 'Claimed',
        Submission.expires_at <= soon,
        Submission.expires_at > datetime.utcnow(),
    ).all()
    for sub in claims:
        create_notification(
            title='Mission deadline approaching',
            body=f'"{sub.task.title}" expires soon — submit your proof before time runs out.',
            audience_type='specific_tester',
            target_user_id=sub.user_id,
            is_automated=True,
            automation_key=f'deadline:{sub.id}',
        )
