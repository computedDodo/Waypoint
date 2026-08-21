import json
import os
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from app import csrf

main_bp = Blueprint('main', __name__)

REVIEWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reviews.json')
MAX_REVIEWS_RETURNED = 30


def _load_reviews():
    if not os.path.exists(REVIEWS_FILE):
        return []
    try:
        with open(REVIEWS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_reviews(reviews):
    with open(REVIEWS_FILE, 'w', encoding='utf-8') as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)


@main_bp.route('/')
def index():
    return render_template('index.html', current_year=datetime.utcnow().year)


@main_bp.route('/info')
def info():
    return render_template('info.html', current_year=datetime.utcnow().year)


# ==========================================
# Public reviews — flagged in chat as the one necessary backend touch.
# GET is open to everyone; POST is CSRF-exempt because it's a public,
# unauthenticated endpoint (same trust level as a contact form), guarded
# instead by a honeypot field and basic validation. No admin auth, so
# moderation is manual — edit reviews.json directly to remove anything.
# ==========================================
@main_bp.route('/api/reviews', methods=['GET'])
def get_reviews():
    reviews = _load_reviews()
    return jsonify(list(reversed(reviews))[:MAX_REVIEWS_RETURNED])


@main_bp.route('/api/reviews', methods=['POST'])
@csrf.exempt
def post_review():
    data = request.get_json(silent=True) or {}

    name = str(data.get('name', '')).strip()[:60]
    role = str(data.get('role', '')).strip()[:30]
    message = str(data.get('message', '')).strip()[:500]
    honeypot = str(data.get('website', '')).strip()

    if honeypot:
        # Looks like a bot filled the hidden field — pretend success, drop it.
        return jsonify({'ok': True})

    try:
        rating = int(data.get('rating'))
    except (TypeError, ValueError):
        rating = 0

    if not name or not message or rating < 1 or rating > 5:
        return jsonify({'ok': False, 'error': 'Add your name, a 1-5 star rating, and a message.'}), 400

    reviews = _load_reviews()
    next_id = max((r.get('id', 0) for r in reviews), default=0) + 1
    reviews.append({
        'id': next_id,
        'name': name,
        'role': role or 'Waypoint user',
        'rating': rating,
        'message': message,
        'created_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
    })
    _save_reviews(reviews)

    return jsonify({'ok': True})
