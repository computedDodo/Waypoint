import os
import requests
import logging

logger = logging.getLogger(__name__)

def send_brevo_email(to_email, subject, text_content):
    """Sends an email using the Brevo v3 REST API."""
    url = "https://api.brevo.com/v3/smtp/email"
    
    api_key = os.environ.get('BREVO_API_KEY')
    sender_email = os.environ.get('MAIL_DEFAULT_SENDER')
    
    if not api_key or not sender_email:
        raise ValueError("BREVO_API_KEY or MAIL_DEFAULT_SENDER is missing.")

    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    
    payload = {
        "sender": {"email": sender_email, "name": "Waypoint"},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_content
    }
    
    try:
        # 10-second timeout prevents infinite hanging
        response = requests.post(url, json=payload, headers=headers, timeout=10.0)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Brevo API Error for {to_email}: {e}")
        if getattr(e, 'response', None) is not None:
            logger.error(f"Brevo Response: {e.response.text}")
        raise e
