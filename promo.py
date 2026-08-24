import json
import os
from datetime import datetime, date

PROMO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'promo_config.json')

DEFAULTS = {
    'active': False,
    'deadline': None,   # 'YYYY-MM-DD', or None for no auto-expiry
    'points_pool': 0,
    'sponsor': '',
}


def load_promo_config():
    if not os.path.exists(PROMO_FILE):
        return dict(DEFAULTS)
    try:
        with open(PROMO_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged


def save_promo_config(config):
    with open(PROMO_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)


def is_promo_live():
    """True only if the toggle is on AND (no deadline set, or today is on/
    before it). An admin who forgets to switch it off after the deadline
    is covered automatically — the banner turns itself off on time."""
    config = load_promo_config()
    if not config.get('active'):
        return False
    deadline = config.get('deadline')
    if deadline:
        try:
            deadline_date = datetime.strptime(deadline, '%Y-%m-%d').date()
            if date.today() > deadline_date:
                return False
        except ValueError:
            pass
    return True
