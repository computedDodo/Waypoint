from app import create_app, db
from models import User

app = create_app()

with app.app_context():
    admin_user = User.query.filter_by(username='admin').first()

    if not admin_user:
        admin = User(
            username='admin',
            email='admin@example.com',
            role='Admin',
            account_status='Active',
        )
        admin.set_password('change-this-password')
        db.session.add(admin)
        db.session.commit()
        print("Admin account created.")
        print("Username: admin")
        print("Password: change-this-password  (change it after first login)")
    else:
        print("Admin account already exists.")
