from functools import wraps
from flask import session, flash, redirect, url_for

# Admin absorbs the old "Campaign Manager" duties too — for a small team,
# one merged role plus three narrower ones (Reviewer, Finance, Support) is
# simpler than five. Splitting Admin back into two roles later is just a
# change to this map, not a rebuild, if you ever need it.
ROLE_PERMISSIONS = {
    'Admin': {
        'clients.manage', 'campaigns.manage', 'reviews.manage', 'payouts.manage',
        'access.manage', 'support.manage', 'staff.manage',
    },
    'Reviewer': {'reviews.manage'},
    'Finance': {'payouts.manage'},
    'Support': {'access.manage', 'support.manage'},
}

STAFF_ROLES = set(ROLE_PERMISSIONS.keys())


def has_permission(permission):
    role = session.get('role')
    return permission in ROLE_PERMISSIONS.get(role, set())


def staff_required(f):
    """Any logged-in staff member, regardless of which specific role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') not in STAFF_ROLES:
            flash('Access denied. Staff login required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def permission_required(*permissions):
    """Staff member must hold at least one of the given permissions."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session or session.get('role') not in STAFF_ROLES:
                flash('Access denied. Staff login required.', 'danger')
                return redirect(url_for('auth.login'))
            allowed = ROLE_PERMISSIONS.get(session.get('role'), set())
            if not any(p in allowed for p in permissions):
                flash("Access denied. Your role doesn't cover this.", 'danger')
                return redirect(url_for('admin.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator
