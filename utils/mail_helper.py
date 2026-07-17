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

COMPANY_NAME_FIRST = os.getenv('COMPANY_NAME_FRONT', 'Bub')
COMPANY_LAST_NAME = os.getenv('COMPANY_NAME_BACK', 'bl')

def is_valid_email(email):
    """
    Checks syntax and deliverability (MX records) of an email.
    Returns: (is_valid: bool, result: str)
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

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = support_email
    msg['Subject'] = f"New Contact Request: {subject}"
    
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
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls() 
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
    
    # 2. USE NORMAL PYTHON F-STRINGS HERE
    platform_name = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME} Support Team" 

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
    # 3. FIX THE SUBJECT F-STRING
    subject = f"You've been invited to {COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME}"
    body = f"Hi {user_name},\n\nYou have been invited to join the team dashboard.\n\nLogin Email: {target_email}\nTemporary Password: {plain_password}\n\nPlease log in and change your password immediately."
    
    try:
        # NOTE: Your send_invite_email is currently missing the actual SMTP sending logic! 
        # Make sure you add the smtplib code here later.
        return True
    except Exception:
        return False

def generate_otp():
    """Generates a random 6-digit OTP string."""
    return str(random.randint(100000, 999999))

def send_otp_email(to_email, otp_code):
    """Sends the OTP email via SMTP."""

    # 4. FIX THE OTP HTML TEMPLATE
    html_content = f"""
    <div style="font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #eee; border-radius: 10px;">
        <h2 style="color: #111827;">Your Verification Code</h2>
        <p style="color: #4b5563; font-size: 16px;">Please use the following 6-digit code to verify your {COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME} account:</p>
        <div style="background: #f9fafb; padding: 15px; text-align: center; border-radius: 8px; margin: 20px 0;">
            <strong style="font-size: 32px; letter-spacing: 4px; color: #E8722A;">{otp_code}</strong>
        </div>
        <p style="color: #9ca3af; font-size: 13px;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    # 5. FIX THE SUBJECT
    msg["Subject"] = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME} - Your Verification Code"
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



def _send_html_email(to_email, subject, html_content):
    """Internal helper to send an HTML email via Gmail SMTP."""
    smtp_user = os.getenv('EMAIL_ADDRESS')
    smtp_password = os.getenv('EMAIL_PASSWORD')
    platform_name = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{platform_name} <{smtp_user}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"SMTP Error sending email to {to_email}: {e}")
        return False


def send_payment_receipt(to_email, plan_name, amount, currency="INR", transaction_id=None):
    """Sends a payment/subscription receipt to the paying customer."""
    platform_name = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME}"
    plan_label = (plan_name or "").capitalize()
    amount_str = f"{currency} {amount:,.2f}" if isinstance(amount, (int, float)) else f"{currency} {amount}"
    txn_row = f"""
        <tr>
            <td style="padding: 6px 0; color: #6b7280;">Transaction ID</td>
            <td style="padding: 6px 0; text-align: right; color: #111827; font-weight: 600;">{transaction_id}</td>
        </tr>""" if transaction_id else ""

    html_content = f"""
    <div style="font-family: sans-serif; padding: 24px; max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #eee; border-radius: 12px;">
        <h2 style="color: #111827; margin-top: 0;">Payment Successful &#127881;</h2>
        <p style="color: #4b5563; font-size: 15px;">Thank you for subscribing to <strong>{platform_name}</strong>. Your <strong>{plan_label}</strong> plan is now active.</p>
        <div style="background: #f9fafb; padding: 18px 20px; border-radius: 10px; margin: 20px 0;">
            <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                <tr>
                    <td style="padding: 6px 0; color: #6b7280;">Plan</td>
                    <td style="padding: 6px 0; text-align: right; color: #111827; font-weight: 600;">{plan_label}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #6b7280;">Amount</td>
                    <td style="padding: 6px 0; text-align: right; color: #E8722A; font-weight: 700;">{amount_str}</td>
                </tr>{txn_row}
            </table>
        </div>
        <p style="color: #4b5563; font-size: 14px;">You can manage your subscription and view usage anytime from your profile dashboard.</p>
        <p style="color: #9ca3af; font-size: 13px;">If you have any questions, just reply to this email.</p>
        <p style="color: #4b5563; font-size: 14px; margin-top: 24px;">— The {platform_name} Team</p>
    </div>
    """
    return _send_html_email(to_email, f"Your {platform_name} {plan_label} receipt", html_content)


def send_sale_notification(plan_name, amount, currency="INR", org_name=None, customer_email=None, transaction_id=None):
    """Notifies the admin/founder that a sale just happened."""
    platform_name = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME}"
    admin_email = os.getenv('SUPER_ADMIN_MAIL') or os.getenv('SUPPORT_EMAIL') or os.getenv('EMAIL_ADDRESS')
    plan_label = (plan_name or "").capitalize()
    amount_str = f"{currency} {amount:,.2f}" if isinstance(amount, (int, float)) else f"{currency} {amount}"

    html_content = f"""
    <div style="font-family: sans-serif; padding: 24px; max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #eee; border-radius: 12px;">
        <h2 style="color: #16a34a; margin-top: 0;">&#128176; New Sale!</h2>
        <p style="color: #4b5563; font-size: 15px;">A customer just subscribed on <strong>{platform_name}</strong>.</p>
        <div style="background: #f0fdf4; padding: 18px 20px; border-radius: 10px; margin: 20px 0;">
            <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                <tr><td style="padding: 6px 0; color: #6b7280;">Plan</td><td style="padding: 6px 0; text-align: right; color: #111827; font-weight: 600;">{plan_label}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">Amount</td><td style="padding: 6px 0; text-align: right; color: #16a34a; font-weight: 700;">{amount_str}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">Customer</td><td style="padding: 6px 0; text-align: right; color: #111827;">{customer_email or 'N/A'}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">Organization</td><td style="padding: 6px 0; text-align: right; color: #111827;">{org_name or 'N/A'}</td></tr>
                <tr><td style="padding: 6px 0; color: #6b7280;">Transaction</td><td style="padding: 6px 0; text-align: right; color: #111827;">{transaction_id or 'N/A'}</td></tr>
            </table>
        </div>
    </div>
    """
    return _send_html_email(admin_email, f"[{platform_name}] New {plan_label} sale — {amount_str}", html_content)



def send_plan_upgrade_email(to_email, user_name, plan_name):
    """Notify a user that their plan was upgraded/changed by the team (super admin)."""
    platform_name = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME}"
    plan_label = (plan_name or "").capitalize()
    greeting = f"Hi {user_name}," if user_name else "Hi there,"

    if (plan_name or "").lower() == "free":
        headline = "Your plan has been updated"
        intro = f"Your <strong>{platform_name}</strong> account has been set to the <strong>Free</strong> plan."
    else:
        headline = "Your plan has been upgraded &#127881;"
        intro = f"Great news! Your <strong>{platform_name}</strong> account has been upgraded to the <strong>{plan_label}</strong> plan."

    html_content = f"""
    <div style="font-family: sans-serif; padding: 24px; max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #eee; border-radius: 12px;">
        <h2 style="color: #111827; margin-top: 0;">{headline}</h2>
        <p style="color: #4b5563; font-size: 15px;">{greeting}</p>
        <p style="color: #4b5563; font-size: 15px;">{intro}</p>
        <div style="background: #f9fafb; padding: 18px 20px; border-radius: 10px; margin: 20px 0;">
            <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                <tr>
                    <td style="padding: 6px 0; color: #6b7280;">New Plan</td>
                    <td style="padding: 6px 0; text-align: right; color: #E8722A; font-weight: 700;">{plan_label}</td>
                </tr>
            </table>
        </div>
        <p style="color: #4b5563; font-size: 14px;">Your new limits are active immediately. You can view your usage and plan details anytime from your profile dashboard.</p>
        <p style="color: #9ca3af; font-size: 13px;">If you have any questions, just reply to this email.</p>
        <p style="color: #4b5563; font-size: 14px; margin-top: 24px;">&mdash; The {platform_name} Team</p>
    </div>
    """
    return _send_html_email(to_email, f"Your {platform_name} plan is now {plan_label}", html_content)


def send_custom_email(to_email, subject, message, user_name=None):
    """Send an arbitrary custom email to a user (composed from the super admin panel)."""
    platform_name = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME}"
    # Preserve line breaks from the composer as HTML line breaks.
    safe_body = (message or "").replace("\n", "<br>")
    greeting = f"<p style='color:#4b5563;font-size:15px;'>Hi {user_name},</p>" if user_name else ""

    html_content = f"""
    <div style="font-family: sans-serif; padding: 24px; max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #eee; border-radius: 12px;">
        {greeting}
        <div style="color: #374151; font-size: 15px; line-height: 1.6;">{safe_body}</div>
        <p style="color: #9ca3af; font-size: 13px; margin-top: 28px; border-top: 1px solid #eee; padding-top: 14px;">Sent by the {platform_name} team.</p>
    </div>
    """
    return _send_html_email(to_email, subject, html_content)



def send_expiry_reminder_email(to_email, user_name, current_plan, fallback_plan, expires_at, days_remaining, reminder_type):
    """
    Sends a subscription expiry reminder email.

    Two scenarios:
    1. Free user was gifted a plan → "Your gifted plan expires on X, you'll revert to Free"
    2. Paid user was gifted a BIGGER plan → "Your upgraded plan expires on X, you'll return to [original plan]"

    Args:
        to_email: Recipient email
        user_name: Recipient name
        current_plan: The plan they're currently on (the gifted one)
        fallback_plan: What they'll fall back to ('free' or their original paid plan)
        expires_at: datetime when plan expires
        days_remaining: 7, 1, or 0
        reminder_type: '7_day', '1_day', or 'today'
    """
    platform_name = f"{COMPANY_NAME_FIRST}.{COMPANY_LAST_NAME}"
    current_label = (current_plan or "").capitalize()
    fallback_label = (fallback_plan or "free").capitalize()
    expiry_date_str = expires_at.strftime('%B %d, %Y') if expires_at else 'soon'
    greeting = f"Hi {user_name}," if user_name else "Hi there,"

    # Determine urgency styling
    if reminder_type == '7_day':
        urgency_color = '#f59e0b'  # Amber
        urgency_label = '7 days remaining'
        subject_prefix = 'Reminder'
    elif reminder_type == '1_day':
        urgency_color = '#ef4444'  # Red
        urgency_label = 'Expires tomorrow'
        subject_prefix = 'Final Notice'
    else:
        urgency_color = '#ef4444'
        urgency_label = 'Expires today'
        subject_prefix = 'Plan Expiring Today'

    # Determine message based on fallback scenario
    if fallback_plan == 'free':
        # Scenario 1: They were on free, got gifted a plan
        headline = f"Your {current_label} plan is expiring"
        main_message = (
            f"Your complimentary <strong>{current_label}</strong> plan on {platform_name} "
            f"will expire on <strong>{expiry_date_str}</strong>."
        )
        fallback_message = (
            f"After expiry, your account will automatically revert to the <strong>Free</strong> plan. "
            f"You'll still have access to basic features, but your limits will be reduced."
        )
        cta_text = "Upgrade to keep your current features"
        cta_note = f"Subscribe to the {current_label} plan (or higher) before {expiry_date_str} to keep all your current features without interruption."
    else:
        # Scenario 2: They were on a paid plan, got gifted a BIGGER plan
        headline = f"Your upgraded {current_label} plan is expiring"
        main_message = (
            f"Your complimentary upgrade to the <strong>{current_label}</strong> plan on {platform_name} "
            f"will expire on <strong>{expiry_date_str}</strong>."
        )
        fallback_message = (
            f"After expiry, your account will return to your <strong>{fallback_label}</strong> plan. "
            f"Your bots, data, and settings will remain intact, but your limits will adjust to the {fallback_label} tier."
        )
        cta_text = f"Upgrade to {current_label} permanently"
        cta_note = f"If you'd like to keep the {current_label} features, you can subscribe to it from your billing page."

    html_content = f"""
    <div style="font-family: sans-serif; padding: 24px; max-width: 600px; margin: 0 auto; background: #fff; border: 1px solid #eee; border-radius: 12px;">
        <div style="background: {urgency_color}; color: #fff; padding: 8px 14px; border-radius: 8px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; margin-bottom: 16px;">
            {urgency_label}
        </div>

        <h2 style="color: #111827; margin-top: 0; font-size: 20px;">{headline}</h2>

        <p style="color: #4b5563; font-size: 15px;">{greeting}</p>
        <p style="color: #4b5563; font-size: 15px;">{main_message}</p>

        <div style="background: #fef3cd; border: 1px solid #fde68a; padding: 16px 20px; border-radius: 10px; margin: 20px 0;">
            <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                <tr>
                    <td style="padding: 6px 0; color: #92400e;">Current Plan</td>
                    <td style="padding: 6px 0; text-align: right; color: #92400e; font-weight: 700;">{current_label}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #92400e;">Expires On</td>
                    <td style="padding: 6px 0; text-align: right; color: #92400e; font-weight: 700;">{expiry_date_str}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #92400e;">After Expiry</td>
                    <td style="padding: 6px 0; text-align: right; color: #92400e; font-weight: 700;">{fallback_label} Plan</td>
                </tr>
            </table>
        </div>

        <p style="color: #4b5563; font-size: 14px;">{fallback_message}</p>

        <div style="background: #f0fdf4; border: 1px solid #bbf7d0; padding: 14px 18px; border-radius: 10px; margin: 20px 0;">
            <p style="color: #166534; font-size: 14px; font-weight: 600; margin: 0 0 6px 0;">{cta_text}</p>
            <p style="color: #166534; font-size: 13px; margin: 0;">{cta_note}</p>
        </div>

        <p style="color: #9ca3af; font-size: 13px;">If you have any questions, just reply to this email or contact us at {os.getenv('SUPPORT_EMAIL', 'support@bubbl.ooo')}.</p>
        <p style="color: #4b5563; font-size: 14px; margin-top: 24px;">&mdash; The {platform_name} Team</p>
    </div>
    """
    subject = f"[{subject_prefix}] Your {platform_name} {current_label} plan expires on {expiry_date_str}"
    return _send_html_email(to_email, subject, html_content)
