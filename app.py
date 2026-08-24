from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail
from flask_wtf import CSRFProtect
from flask_migrate import Migrate
from dotenv import load_dotenv
from config import Config

load_dotenv()

db = SQLAlchemy()
mail = Mail()
csrf = CSRFProtect()
migrate = Migrate()


def format_naira(value):
    try:
        return f"₦{float(value):,.2f}"
    except (TypeError, ValueError):
        return "₦0.00"


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)

    app.jinja_env.filters['naira'] = format_naira

    from permissions import has_permission
    app.jinja_env.globals['has_permission'] = has_permission

    from auth import auth_bp
    from admin import admin_bp
    from tasks import tasks_bp
    from main import main_bp
    from clients import clients_bp
    from campaigns import campaigns_bp
    from client_portal import client_portal_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(client_portal_bp)

    @app.before_request
    def _tick_automations():
        # Cheap "lazy cron" check — see notifications.py. Only does real
        # work once per hour; every other request just reads one row.
        # Wrapped so a problem here (e.g. migrations not yet applied)
        # can't take down every other page on the site.
        try:
            from notifications import run_due_automations
            run_due_automations()
        except Exception as e:
            db.session.rollback()
            app.logger.warning(f"Automation tick failed, continuing anyway: {e}")

    @app.context_processor
    def _inject_unread_count():
        from flask import session
        from models import NotificationRecipient
        count = 0
        if 'client_id' in session:
            count = NotificationRecipient.query.filter_by(
                client_id=session['client_id'], read_at=None).count()
        elif session.get('user_id') and session.get('role') == 'Tester':
            count = NotificationRecipient.query.filter_by(
                user_id=session['user_id'], read_at=None).count()
        return dict(unread_notification_count=count)

    @app.context_processor
    def _inject_promo():
        from promo import load_promo_config, is_promo_live
        config = load_promo_config()
        return dict(
            promo_active=is_promo_live(),
            promo_deadline=config.get('deadline'),
            promo_points_pool=config.get('points_pool'),
            promo_sponsor=config.get('sponsor'),
        )

    return app
