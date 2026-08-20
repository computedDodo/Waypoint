from datetime import datetime, timedelta
import random
from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_mail import Message
from models import User
from app import db, mail
from permissions import STAFF_ROLES

auth_bp = Blueprint('auth', __name__)

RESET_TOKEN_MINUTES = 30


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        email = request.form.get('email').strip()
        password = request.form.get('password')
        dob_raw = request.form.get('date_of_birth', '').strip()

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('auth.register'))

        dob = None
        if dob_raw:
            try:
                dob = datetime.strptime(dob_raw, '%Y-%m-%d').date()
            except ValueError:
                flash('That date of birth doesn\'t look right.', 'danger')
                return redirect(url_for('auth.register'))

        if not dob:
            flash('Date of birth is required.', 'danger')
            return redirect(url_for('auth.register'))

        new_user = User(username=username, email=email, account_status='Pending Email', date_of_birth=dob)
        new_user.set_password(password)

        verification_method = random.choice(['otp', 'token', 'both'])
        new_user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)

        email_body = f"Hello {username},\n\nWelcome to Waypoint!\n\n"

        if verification_method in ['otp', 'both']:
            otp_code = new_user.generate_otp()
            email_body += f"Your verification code is: {otp_code}\n\n"

        if verification_method in ['token', 'both']:
            token = new_user.generate_token()
            verify_link = url_for('auth.verify_link', token=token, _external=True)
            email_body += f"Click the link below to verify your account:\n{verify_link}\n\n"

        email_body += "Note: This verification step expires in 15 minutes."

        db.session.add(new_user)
        db.session.commit()

        try:
            msg = Message(subject="Verify your Waypoint account", recipients=[email], body=email_body)
            mail.send(msg)
            flash('Registration successful! Please check your email to verify your account.', 'success')
            return redirect(url_for('auth.verify_prompt', email=email))
        except Exception as e:
            db.session.delete(new_user)
            db.session.commit()
            flash('An error occurred sending the verification email. Please try again.', 'danger')
            print(f"Mail Error: {e}")
            return redirect(url_for('auth.register'))

    return render_template('auth/register.html')


@auth_bp.route('/verify', methods=['GET', 'POST'])
def verify_prompt():
    email = request.args.get('email')

    if not email:
        flash('Invalid request.', 'danger')
        return redirect(url_for('auth.register'))

    user = User.query.filter_by(email=email).first()

    if not user or user.account_status != 'Pending Email':
        flash('Account already verified or does not exist.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        submitted_otp = request.form.get('otp', '').strip()

        if datetime.utcnow() > user.verification_expires_at:
            flash('Your verification code has expired. Please request a new one.', 'danger')
            return redirect(url_for('auth.verify_prompt', email=email))

        if submitted_otp and submitted_otp == user.verification_otp:
            user.account_status = 'Pending Approval'
            user.verification_otp = None
            user.verification_token = None
            db.session.commit()
            flash('Email verified! Your account is now waiting for admin approval.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('Invalid OTP code. Try again.', 'danger')

    return render_template('auth/verify.html', email=email)


@auth_bp.route('/verify/<token>')
def verify_link(token):
    user = User.query.filter_by(verification_token=token).first()

    if not user:
        flash('Invalid or expired verification link.', 'danger')
        return redirect(url_for('auth.register'))

    if user.account_status != 'Pending Email':
        flash('Account already verified.', 'warning')
        return redirect(url_for('auth.login'))

    if datetime.utcnow() > user.verification_expires_at:
        flash('Your verification link has expired. Please request a new one.', 'danger')
        return redirect(url_for('auth.verify_prompt', email=user.email))

    user.account_status = 'Pending Approval'
    user.verification_otp = None
    user.verification_token = None
    db.session.commit()

    flash('Email verified successfully! Your account is now waiting for admin approval.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/resend-verification')
def resend_verification():
    email = request.args.get('email')
    user = User.query.filter_by(email=email).first()

    if not user or user.account_status != 'Pending Email':
        flash('Invalid request.', 'danger')
        return redirect(url_for('auth.register'))

    verification_method = random.choice(['otp', 'token', 'both'])
    user.verification_expires_at = datetime.utcnow() + timedelta(minutes=15)

    email_body = f"Hello {user.username},\n\nHere is your new verification step.\n\n"

    if verification_method in ['otp', 'both']:
        otp_code = user.generate_otp()
        email_body += f"Your verification code is: {otp_code}\n\n"

    if verification_method in ['token', 'both']:
        token = user.generate_token()
        verify_link = url_for('auth.verify_link', token=token, _external=True)
        email_body += f"Click the link below to verify your account:\n{verify_link}\n\n"

    email_body += "Note: This verification step expires in 15 minutes."

    db.session.commit()

    try:
        msg = Message(subject="New verification code", recipients=[email], body=email_body)
        mail.send(msg)
        flash('A new verification step has been sent to your email.', 'success')
    except Exception:
        flash('Failed to resend email. Please try again later.', 'danger')

    return redirect(url_for('auth.verify_prompt', email=email))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['role'] = user.role

            if user.role in STAFF_ROLES:
                return redirect(url_for('admin.dashboard'))
            elif user.account_status == 'Active':
                return redirect(url_for('tasks.bounty_board'))
            else:
                flash(f'Account status: {user.account_status}. Please wait for admin approval.', 'warning')
                return redirect(url_for('auth.login'))
        else:
            flash('Invalid username or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))


# ==========================================
# PASSWORD RESET
# ==========================================
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        # Same message either way — don't reveal whether an account exists.
        if user:
            token = user.generate_reset_token()
            user.reset_expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES)
            db.session.commit()

            reset_link = url_for('auth.reset_password', token=token, _external=True)
            body = (
                f"Hello {user.username},\n\n"
                f"Click the link below to set a new password. It expires in "
                f"{RESET_TOKEN_MINUTES} minutes:\n{reset_link}\n\n"
                "If you didn't request this, you can ignore this email."
            )
            try:
                mail.send(Message(subject="Reset your Waypoint password", recipients=[user.email], body=body))
            except Exception as e:
                print(f"Mail Error: {e}")

        flash('If that account exists, a reset link has been sent to its email.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.reset_expires_at or datetime.utcnow() > user.reset_expires_at:
        flash('That reset link is invalid or has expired. Request a new one.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return redirect(url_for('auth.reset_password', token=token))

        if password != confirm:
            flash("Passwords don't match.", 'danger')
            return redirect(url_for('auth.reset_password', token=token))

        user.set_password(password)
        user.reset_token = None
        user.reset_expires_at = None
        db.session.commit()

        flash('Password updated. Sign in with your new password.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)
