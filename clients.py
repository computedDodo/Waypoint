from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_mail import Message
from models import Client, Campaign
from permissions import permission_required
from app import db, mail

clients_bp = Blueprint('clients', __name__, url_prefix='/admin/clients')

INVITE_TOKEN_HOURS = 72


def _send_invite(client):
    """Emails the client a link to set their portal password. Reuses the
    same reset-token fields Client shares the shape of with User."""
    if not client.contact_email:
        return False
    token = client.generate_reset_token()
    client.reset_expires_at = datetime.utcnow() + timedelta(hours=INVITE_TOKEN_HOURS)
    db.session.commit()

    invite_link = url_for('client_portal.reset_password', token=token, _external=True)
    body = (
        f"Hello {client.contact_name or client.company_name},\n\n"
        f"You now have access to the Waypoint client portal for {client.company_name}. "
        f"Set your password here (link expires in {INVITE_TOKEN_HOURS} hours):\n{invite_link}"
    )
    try:
        mail.send(Message(subject="Your Waypoint client portal access", recipients=[client.contact_email], body=body))
        return True
    except Exception as e:
        print(f"Mail Error: {e}")
        return False


@clients_bp.route('/')
@permission_required('clients.manage')
def list_clients():
    clients = Client.query.order_by(Client.created_at.desc()).all()
    return render_template('admin/clients_list.html', clients=clients)


@clients_bp.route('/new', methods=['GET', 'POST'])
@permission_required('clients.manage')
def new_client():
    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip()
        contact_name = request.form.get('contact_name', '').strip()
        contact_email = request.form.get('contact_email', '').strip()
        notes = request.form.get('notes', '').strip()

        if not company_name:
            flash('Company name is required.', 'danger')
            return redirect(url_for('clients.new_client'))

        client = Client(
            company_name=company_name,
            contact_name=contact_name,
            contact_email=contact_email,
            notes=notes,
        )
        db.session.add(client)
        db.session.commit()

        if contact_email and _send_invite(client):
            flash(f'Added client "{company_name}" and sent a portal invite to {contact_email}.', 'success')
        elif contact_email:
            flash(f'Added client "{company_name}", but the invite email failed — resend it from their page.', 'warning')
        else:
            flash(f'Added client "{company_name}". Add a contact email to invite them to the portal.', 'success')

        return redirect(url_for('clients.view_client', client_id=client.id))

    return render_template('admin/client_new.html')


@clients_bp.route('/<int:client_id>')
@permission_required('clients.manage')
def view_client(client_id):
    client = Client.query.get_or_404(client_id)
    campaigns = client.campaigns.order_by(Campaign.created_at.desc()).all()
    return render_template('admin/client_detail.html', client=client, campaigns=campaigns)


@clients_bp.route('/<int:client_id>/resend-invite', methods=['POST'])
@permission_required('clients.manage')
def resend_invite(client_id):
    client = Client.query.get_or_404(client_id)
    if not client.contact_email:
        flash('Add a contact email for this client first.', 'danger')
    elif _send_invite(client):
        flash(f'Portal invite sent to {client.contact_email}.', 'success')
    else:
        flash('The invite email failed to send.', 'danger')
    return redirect(url_for('clients.view_client', client_id=client.id))
