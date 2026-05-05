import os, re
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from email_validator import validate_email, EmailNotValidError

load_dotenv()

EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

def is_valid_email(email):
    """
    Checks syntax and deliverability (MX records) of an email.
    Returns: (is_valid: bool, result: str)
    If valid, result is the normalized email.
    If invalid, result is the human-readable error message.
    """
    try:
        valid = validate_email(email, check_deliverability=True)
        return True, valid.normalized
        
    except EmailNotValidError as e:
        return False, str(e)

def send_contact_email(sender_name, sender_email, subject, message):
    """
    Sends the contact form data to your support email via SMTP.
    """
    smtp_server = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('MAIL_PORT', 587))
    smtp_user = os.getenv('EMAIL_ADDRESS')
    smtp_password = os.getenv('EMAIL_PASSWORD')    
    support_email = os.getenv('SUPPORT_EMAIL', smtp_user) 

    # Create the email structure
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = support_email
    msg['Subject'] = f"New Contact Request: {subject}"
    
    # Format the body to look professional
    body = f"""
You have received a new message from your platform's contact form.

Details:
----------------------------------------
Name: {sender_name}
Email: {sender_email}
Subject: {subject}
----------------------------------------

Message:
{message}
"""
    msg.attach(MIMEText(body, 'plain'))

    try:
        # Establish a secure connection and send
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls() # Secure the connection
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP Error sending contact email: {e}")
        return False

def send_auto_reply(user_name, user_email):
    """
    Sends a professional automated acknowledgment email back to the user.
    """
    smtp_server = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('MAIL_PORT', 587))
    smtp_user = os.getenv('EMAIL_ADDRESS')
    smtp_password = os.getenv('EMAIL_PASSWORD')
    
    platform_name = "{config.COMPANY_NAME_FIRST}.{config.COMPANY_LAST_NAME} Support Team" 

    msg = MIMEMultipart()
    msg['From'] = f"{platform_name} <{smtp_user}>"
    msg['To'] = user_email
    msg['Subject'] = "We've received your message!"
    
    body = f"""Hi {user_name},

Thank you for reaching out to us! 

This is an automated response to let you know that we have successfully received your message. Our support team is reviewing your inquiry and will get back to you as soon as possible (usually within 24 hours).

For your records, here is a copy of the information you submitted:
Email: {user_email}

If you have any additional details to add, feel free to reply directly to this email.

Best regards,
The {platform_name}
"""
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP Error sending auto-reply: {e}")
        return False

def send_invite_email(target_email, user_name, plain_password):
    subject = "You've been invited to {config.COMPANY_NAME_FIRST}.{config.COMPANY_LAST_NAME}"
    body = f"Hi {user_name},\n\nYou have been invited to join the team dashboard.\n\nLogin Email: {target_email}\nTemporary Password: {plain_password}\n\nPlease log in and change your password immediately."
    
    try:
        return True
    except Exception:
        return False

def generate_otp():
    """Generates a random 6-digit OTP string."""
    return str(random.randint(100000, 999999))

def send_otp_email(to_email, otp_code):
    """Sends the OTP email via SMTP."""

    html_content = f"""
    <div style="font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #111827;">Your Verification Code</h2>
        <p style="color: #4b5563; font-size: 16px;">Please use the following 6-digit code to verify your {config.COMPANY_NAME_FIRST}.{config.COMPANY_LAST_NAME} account:</p>
        <div style="background: #f9fafb; padding: 15px; text-align: center; border-radius: 8px; margin: 20px 0;">
            <strong style="font-size: 32px; letter-spacing: 4px; color: #E8722A;">{otp_code}</strong>
        </div>
        <p style="color: #9ca3af; font-size: 13px;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "{config.COMPANY_NAME_FIRST}.{config.COMPANY_LAST_NAME} - Your Verification Code"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())

        return True

    except Exception as e:
        print(f"SMTP Email Error: {e}")
        return False