"""
PolyMarketAlphaAI — Email Service Layer
========================================

Single responsibility: sending emails.

All email sending in the application flows through send_email().
Other functions build HTML templates and delegate to send_email().

Changing providers (SMTP → Resend → SendGrid) requires modifying
only send_email(). Everything else stays untouched.

Python 3.12 | PEP 8 | Typed functions | Production quality
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")

# ─────────────────────────────────────────────────────────────
# CORE EMAIL FUNCTION
# ─────────────────────────────────────────────────────────────


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    from_email: str | None = None,
    reply_to: str | None = None,
) -> dict:
    """
    Send a single HTML email.

    This is the ONLY function that touches SMTP / transport.
    All other email functions in this module delegate here.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        html_body: Full HTML content.
        from_email: Optional override sender address.
        reply_to: Optional Reply-To header.

    Returns:
        {"success": True, "message": "..."}
        or
        {"success": False, "error": "..."}
    """
    if not to_email or not subject or not html_body:
        return {
            "success": False,
            "error": "to_email, subject, and html_body are required.",
        }

    sender = from_email or SMTP_FROM
    if not sender:
        return {
            "success": False,
            "error": "No sender address configured (SMTP_FROM or SMTP_USER).",
        }

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(sender, [to_email], msg.as_string())

        return {
            "success": True,
            "message": f"Email sent to {to_email}",
        }

    except smtplib.SMTPException as exc:
        return {
            "success": False,
            "error": f"SMTP error: {exc}",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"Unexpected error: {exc}",
        }


# ─────────────────────────────────────────────────────────────
# TEMPLATE HELPERS
# ─────────────────────────────────────────────────────────────


def _base_template(title: str, body_html: str, first_name: str | None = None) -> str:
    """Wrap content in a consistent branded HTML email template."""

    greeting = f"<p>Hello {first_name},</p>" if first_name else "<p>Hello,</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #f4f4f5; margin: 0; padding: 20px; }}
        .container {{ max-width: 480px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
        .logo {{ font-size: 20px; font-weight: 700; color: #111827; margin-bottom: 24px; }}
        .code {{ font-size: 32px; font-weight: 700; letter-spacing: 4px; color: #111827; background: #f3f4f6; padding: 16px 24px; border-radius: 8px; display: inline-block; margin: 16px 0; }}
        .footer {{ font-size: 12px; color: #9ca3af; margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 16px; }}
        a {{ color: #2563eb; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">PolyMarketAlphaAI</div>
        {greeting}
        {body_html}
        <div class="footer">
            If you didn't request this email, you can safely ignore it.<br>
            &copy; PolyMarketAlphaAI. All rights reserved.
        </div>
    </div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────
# VERIFICATION CODE EMAIL
# ─────────────────────────────────────────────────────────────


def send_verification_code(
    email: str,
    code: str,
    purpose: str,
    first_name: str | None = None,
) -> dict:
    """
    Send a verification code email.

    The email template adapts automatically based on the purpose:
        - telegram_link   → "Link your Telegram account"
        - password_reset  → "Reset your password"
        - login           → "Login verification"
        - email_verification → "Verify your email"
        - email_change    → "Confirm email change"

    Args:
        email: Recipient email address.
        code: 6-digit plain verification code.
        purpose: Verification purpose (must match DB enum).
        first_name: Optional first name for personalization.

    Returns:
        Result dict from send_email().
    """
    if not email or not code or not purpose:
        return {
            "success": False,
            "error": "email, code, and purpose are required.",
        }

    # Purpose → human-readable title and description
    _purpose_meta: dict[str, dict[str, str]] = {
        "telegram_link": {
            "subject": "Verify your Telegram account",
            "headline": "Link your Telegram account",
            "description": "Use the verification code below to link your Telegram account to PolyMarketAlphaAI.",
        },
        "password_reset": {
            "subject": "Reset your password",
            "headline": "Reset your password",
            "description": "Use the verification code below to reset your password.",
        },
        "login": {
            "subject": "Login verification",
            "headline": "Login verification",
            "description": "Use the verification code below to complete your login.",
        },
        "email_verification": {
            "subject": "Verify your email",
            "headline": "Verify your email address",
            "description": "Use the verification code below to verify your email address.",
        },
        "email_change": {
            "subject": "Confirm email change",
            "headline": "Confirm your new email address",
            "description": "Use the verification code below to confirm your new email address.",
        },
    }

    meta = _purpose_meta.get(purpose, {
        "subject": "Your verification code",
        "headline": "Verification code",
        "description": "Use the verification code below.",
    })

    body = f"""
        <h2 style="margin: 0 0 8px 0; color: #111827;">{meta["headline"]}</h2>
        <p style="color: #4b5563; line-height: 1.6;">{meta["description"]}</p>
        <div style="text-align: center;">
            <div class="code">{code}</div>
        </div>
        <p style="color: #6b7280; font-size: 14px;">
            This code expires in <strong>10 minutes</strong>.
        </p>
    """

    html = _base_template(
        title=meta["subject"],
        body_html=body,
        first_name=first_name,
    )

    return send_email(
        to_email=email,
        subject=meta["subject"],
        html_body=html,
    )


# ─────────────────────────────────────────────────────────────
# PASSWORD RESET
# ─────────────────────────────────────────────────────────────


def send_password_reset(
    email: str,
    code: str,
    first_name: str | None = None,
) -> dict:
    """
    Send a password reset verification code.

    Convenience wrapper around send_verification_code()
    with purpose="password_reset".
    """
    return send_verification_code(
        email=email,
        code=code,
        purpose="password_reset",
        first_name=first_name,
    )


# ─────────────────────────────────────────────────────────────
# WELCOME EMAIL
# ─────────────────────────────────────────────────────────────


def send_welcome_email(
    email: str,
    first_name: str | None = None,
) -> dict:
    """
    Send a welcome email to newly registered users.

    Args:
        email: Recipient email address.
        first_name: Optional first name for personalization.

    Returns:
        Result dict from send_email().
    """
    if not email:
        return {
            "success": False,
            "error": "email is required.",
        }

    body = """
        <h2 style="margin: 0 0 8px 0; color: #111827;">Welcome to PolyMarketAlphaAI</h2>
        <p style="color: #4b5563; line-height: 1.6;">
            Your account has been created successfully. You now have access to:
        </p>
        <ul style="color: #4b5563; line-height: 1.8;">
            <li>AI-powered market research and signals</li>
            <li>Real-time Polymarket analysis</li>
            <li>Telegram and email delivery</li>
            <li>Subscription management</li>
        </ul>
        <p style="color: #4b5563; line-height: 1.6;">
            Get started by linking your Telegram account or exploring the dashboard.
        </p>
    """

    html = _base_template(
        title="Welcome to PolyMarketAlphaAI",
        body_html=body,
        first_name=first_name,
    )

    return send_email(
        to_email=email,
        subject="Welcome to PolyMarketAlphaAI",
        html_body=html,
    )


# ─────────────────────────────────────────────────────────────
# SUBSCRIPTION EMAILS
# ─────────────────────────────────────────────────────────────


def send_subscription_email(
    email: str,
    email_type: str,
    plan_name: str | None = None,
    first_name: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict:
    """
    Send subscription-related emails.

    Args:
        email: Recipient email address.
        email_type: One of:
            - "subscription_started"
            - "subscription_renewed"
            - "subscription_cancelled"
            - "subscription_expiring"
            - "payment_receipt"
            - "token_purchase_receipt"
        plan_name: Name of the subscription plan (if applicable).
        first_name: Optional first name for personalization.
        extra_context: Additional template variables.

    Returns:
        Result dict from send_email().
    """
    if not email or not email_type:
        return {
            "success": False,
            "error": "email and email_type are required.",
        }

    _templates: dict[str, dict[str, str]] = {
        "subscription_started": {
            "subject": "Your subscription has started",
            "headline": "Subscription activated",
            "body": f"""<p>Your <strong>{plan_name or "subscription"}</strong> is now active.</p>
            <p>You now have full access to all premium features, including unlimited AI signals and priority market research.</p>""",
        },
        "subscription_renewed": {
            "subject": "Your subscription has been renewed",
            "headline": "Subscription renewed",
            "body": f"""<p>Your <strong>{plan_name or "subscription"}</strong> has been successfully renewed.</p>
            <p>Thank you for continuing with PolyMarketAlphaAI.</p>""",
        },
        "subscription_cancelled": {
            "subject": "Your subscription has been cancelled",
            "headline": "Subscription cancelled",
            "body": """<p>Your subscription has been cancelled and will not renew.</p>
            <p>You will continue to have access until the end of your current billing period.</p>""",
        },
        "subscription_expiring": {
            "subject": "Your subscription is expiring soon",
            "headline": "Subscription expiring",
            "body": """<p>Your subscription expires in <strong>3 days</strong>.</p>
            <p>Renew now to avoid interruption to your AI signals and market research.</p>""",
        },
        "payment_receipt": {
            "subject": "Payment receipt",
            "headline": "Payment confirmed",
            "body": f"""<p>Thank you for your payment.</p>
            <p>Your <strong>{plan_name or "subscription"}</strong> has been updated.</p>""",
        },
        "token_purchase_receipt": {
            "subject": "Token purchase receipt",
            "headline": "Tokens added to your wallet",
            "body": """<p>Your token purchase has been confirmed.</p>
            <p>The tokens have been added to your wallet and are ready to use.</p>""",
        },
    }

    template = _templates.get(email_type)
    if not template:
        return {
            "success": False,
            "error": f"Unknown email_type: {email_type}",
        }

    # Inject extra context if provided
    body_html = template["body"]
    if extra_context:
        for key, value in extra_context.items():
            body_html = body_html.replace(f"{{{key}}}", str(value))

    full_body = f"""
        <h2 style="margin: 0 0 8px 0; color: #111827;">{template["headline"]}</h2>
        <div style="color: #4b5563; line-height: 1.6;">
            {body_html}
        </div>
    """

    html = _base_template(
        title=template["subject"],
        body_html=full_body,
        first_name=first_name,
    )

    return send_email(
        to_email=email,
        subject=template["subject"],
        html_body=html,
    )


# ─────────────────────────────────────────────────────────────
# SIGNAL COMPLETED NOTIFICATION
# ─────────────────────────────────────────────────────────────


def send_signal_completed(
    email: str,
    market_question: str,
    summary: str,
    confidence_score: float,
    first_name: str | None = None,
    report_url: str | None = None,
) -> dict:
    """
    Send a "research completed" notification email.

    Args:
        email: Recipient email address.
        market_question: The market question that was researched.
        summary: Short executive summary of the research.
        confidence_score: AI confidence score (0.0–1.0).
        first_name: Optional first name for personalization.
        report_url: Optional link to the full report on the dashboard.

    Returns:
        Result dict from send_email().
    """
    if not email or not market_question:
        return {
            "success": False,
            "error": "email and market_question are required.",
        }

    confidence_pct = int(confidence_score * 100)
    confidence_color = "#16a34a" if confidence_score >= 0.7 else "#ca8a04" if confidence_score >= 0.4 else "#dc2626"

    report_link = f"""<p style="margin-top: 16px;">
        <a href="{report_url}" style="display: inline-block; background: #111827; color: #ffffff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 500;">
            View Full Report
        </a>
    </p>""" if report_url else ""

    body = f"""
        <h2 style="margin: 0 0 8px 0; color: #111827;">Research Complete</h2>
        <p style="color: #4b5563; line-height: 1.6;">
            Your AI research on the following market is ready:
        </p>
        <div style="background: #f9fafb; border-left: 4px solid #111827; padding: 16px; border-radius: 0 8px 8px 0; margin: 16px 0;">
            <p style="margin: 0; font-weight: 600; color: #111827;">{market_question}</p>
        </div>
        <p style="color: #4b5563; line-height: 1.6;"><strong>Summary:</strong></p>
        <p style="color: #4b5563; line-height: 1.6;">{summary}</p>
        <p style="color: #4b5563; line-height: 1.6;">
            <strong>Confidence:</strong>
            <span style="color: {confidence_color}; font-weight: 700;">{confidence_pct}%</span>
        </p>
        {report_link}
    """

    html = _base_template(
        title="Research Complete — PolyMarketAlphaAI",
        body_html=body,
        first_name=first_name,
    )

    return send_email(
        to_email=email,
        subject=f"Research Complete: {market_question[:50]}{'...' if len(market_question) > 50 else ''}",
        html_body=html,
    )


# ─────────────────────────────────────────────────────────────
# TOKEN PURCHASE RECEIPT
# ─────────────────────────────────────────────────────────────


def send_token_purchase_receipt(
    email: str,
    tokens_purchased: int,
    amount_paid: str,
    new_balance: float,
    first_name: str | None = None,
) -> dict:
    """
    Send a token purchase receipt email.

    Convenience wrapper that delegates to send_subscription_email().
    """
    return send_subscription_email(
        email=email,
        email_type="token_purchase_receipt",
        first_name=first_name,
        extra_context={
            "tokens_purchased": tokens_purchased,
            "amount_paid": amount_paid,
            "new_balance": new_balance,
        },
    )
