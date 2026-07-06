# ==========================================================
# BEGIN OF FILE telegram_bot.py
# ==========================================================
"""
PolyMarketAlphaAI — Telegram Bot (v2 Architecture)
==================================================

Complete rewrite for the new architecture where:
- Telegram NEVER creates users
- Telegram is ONLY an authentication provider
- Everything uses user_id
- Web is the ONLY account creator

Commands:
    /start   — Check link status, show code if not linked
    /signal  — Request AI analysis for a market
    /set     — Update profile fields
    /status  — Show account status

Python 3.12 | PEP 8 | Typed functions | Production quality
"""

import os

import requests

import VerificationCodeError
import VerificationCodeExpiredError
import VerificationCodeAttemptsExceededError
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db import (
    connect_telegram,
    prepare_signal_request,
    consume_token,
    consume_trial,
    update_profile,
    validate_signal_request,
    get_user_by_id,
    get_user_by_telegram_id,
    telegram_login,
    update_connection_username,
    mark_user_registered,
    get_wallet,
    get_user_subscription,
    get_token_balance,
    get_missing_fields,
    is_profile_complete,
    save_market_research,
    update_signal_status,
    mark_delivery_sent,
    get_pending_signal_requests,
    find_user_by_email,
    create_verification_code,
    verify_verification_code,
    link_telegram_to_user,
    update_user_field,
    get_pending_verification_code,
)
from email_service import send_verification_code
from exceptions import (
    BusinessError,
    MarketNotFoundError,
    MarketClosedError,
    ProfileIncompleteError,
    TrialExpiredError,
    WalletNotFoundError,
    InsufficientTokensError,
    TelegramLinkError,
    EmailNotFoundError,
    VerificationCodeError,
    VerificationCodeExpiredError,
    VerificationCodeAttemptsExceededError,
)

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = os.getenv("RESEARCH_API_URL", "http://localhost:8000/research")

# Required fields for profile completion
REQUIRED_FIELDS = ["email", "first_name", "last_name"]
ALLOWED_SET = REQUIRED_FIELDS

FIELD_MAPPING = {
    "username": "telegram_username",
    "telegram_username": "telegram_username",
    "email": "email",
    "first_name": "first_name",
    "last_name": "last_name",
}

# ─────────────────────────────────────────────────────────────
# CONVERSATION STATES (for email verification linking flow)
# ─────────────────────────────────────────────────────────────

(
    STATE_WAITING_EMAIL,
    STATE_WAITING_CODE,
) = range(2)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────


def build_missing_message(missing: list[str]) -> str:
    """Build a formatted message listing missing profile fields."""
    placeholders = {
        "email": "your@email.com",
        "first_name": "YourFirstName",
        "last_name": "YourLastName",
    }
    lines = ["📋 *Please provide the following:*\n"]
    for field in missing:
        display_name = field.replace("_", " ").title()
        lines.append(f"  `/set {field} {placeholders.get(field, 'value')}`")
    lines.append("\n_Send each command one at a time._")
    return "\n".join(lines)


def build_link_message(code: str) -> str:
    """Build the message shown when Telegram is not linked to an account."""
    return (
        "🔗 *Telegram not linked*\n\n"
        "Your Telegram account is not connected "
        "to any PolyMarketAlphaAI account.\n\n"
        "1️⃣ Login on the website.\n"
        "2️⃣ Open *Settings → Connected Accounts*.\n"
        "3️⃣ Click *Connect Telegram*.\n"
        f"4️⃣ Enter this code:\n\n"
        f"`{code}`\n\n"
        "The code expires in 15 minutes."
    )


def build_email_verification_prompt() -> str:
    """Build the message asking the user for their registered email."""
    return (
        "🔗 *Telegram not linked*\n\n"
        "I couldn't find a linked account for this Telegram profile.\n\n"
        "Please enter the email address you used to register on our website.\n\n"
        "Example:\n"
        "`john@example.com`\n\n"
        "_Or use the website dashboard to connect your Telegram account._"
    )


def build_code_prompt(email: str) -> str:
    """Build the message asking the user for their verification code."""
    masked_email = _mask_email(email)
    return (
        f"📧 *Verification code sent*\n\n"
        f"We've sent a verification code to *{masked_email}*.\n\n"
        "Please enter the 6-digit code.\n\n"
        "The code expires in 10 minutes."
    )


def _mask_email(email: str) -> str:
    """Mask an email address for display: j***@example.com"""
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def _resolve_user(update: Update) -> dict | None:
    """
    Resolve the user from a Telegram update.

    Returns the user dict if linked, or None if not linked.
    Sends the link message automatically if not linked.
    """
    telegram_id = update.effective_user.id
    login = telegram_login(telegram_id)

    if login["status"] == "not_linked":
        return None

    user = login["user"]

    # Auto-update Telegram username if changed
    username = update.effective_user.username or ""
    current_username = user.get("telegram_username") or ""
    if username and username != current_username:
        update_connection_username(user["user_id"], username)
        user = get_user_by_id(user["user_id"])

    return user


# ─────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /start command.

    Workflow:
        telegram_login() → Linked? → Yes → Welcome back
                         → No  → Generate code → Display → Exit
    """
    telegram_id = update.effective_user.id
    login = telegram_login(telegram_id)

    # ── Not linked ──
    if login["status"] == "not_linked":
        await update.message.reply_text(
            build_link_message(login["code"]),
            parse_mode="Markdown",
        )
        return

    # ── Linked ──
    user = login["user"]
    missing = get_missing_fields(user)

    if missing:
        await update.message.reply_text(
            "⚠️ Your profile is incomplete.\n\n"
            + build_missing_message(missing),
            parse_mode="Markdown",
        )
        return

    # Profile complete — mark registered and welcome
    mark_user_registered(user["user_id"])
    user = get_user_by_id(user["user_id"])

    await update.message.reply_text(
        f"👋 Welcome back *{user.get('first_name', '')}*!\n\n"
        "Your Telegram account is connected.\n\n"
        "You can now request signals using\n"
        "`/signal MARKET_ID`",
        parse_mode="Markdown",
    )

    await _resume_pending_signals(update, user)


# ─────────────────────────────────────────────────────────────
# /signal
# ─────────────────────────────────────────────────────────────


async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """
    Handle /signal command.

    If the Telegram account is not linked, starts the email verification
    conversation flow instead of just showing a link code.
    """
    args = context.args

    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Usage:\n"
            "`/signal MARKET_ID`\n\n"
            "Example:\n"
            "`/signal 54085`",
            parse_mode="Markdown",
        )
        return None

    m_id = int(args[0])

    # Store the original command args so we can retry after linking
    context.user_data["pending_signal_m_id"] = m_id

    login = telegram_login(update.effective_user.id)

    if login["status"] == "not_linked":
        # Start the email verification conversation
        await update.message.reply_text(
            build_email_verification_prompt(),
            parse_mode="Markdown",
        )
        return STATE_WAITING_EMAIL

    user = login["user"]

    try:
        result = prepare_signal_request(
            user=user,
            m_id=m_id,
        )

    except MarketNotFoundError:
        await update.message.reply_text(
            f"❌ Market `{m_id}` not found.",
            parse_mode="Markdown",
        )
        return None

    except MarketClosedError:
        await update.message.reply_text(
            "❌ This market is already closed."
        )
        return None

    except ProfileIncompleteError:
        await update.message.reply_text(
            build_missing_message(
                get_missing_fields(user)
            ),
            parse_mode="Markdown",
        )
        return None

    except TrialExpiredError:
        await update.message.reply_text(
            "❌ Your free trial has expired."
        )
        return None

    except InsufficientTokensError:
        await update.message.reply_text(
            "❌ Insufficient token balance."
        )
        return None

    except BusinessError as e:
        await update.message.reply_text(str(e))
        return None

    signal_request = result["request"]
    market = result["market"]
    account_type = result["account_type"]

    await _execute_signal(
        update=update,
        user=user,
        market=market,
        m_id=m_id,
        signal_req=signal_request,
        account_type=account_type,
    )

    # Clear pending signal after successful execution
    context.user_data.pop("pending_signal_m_id", None)
    return None


# ─────────────────────────────────────────────────────────────
# CONVERSATION HANDLER — Email Verification Linking Flow
# ─────────────────────────────────────────────────────────────


async def _handle_email_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """
    Step 2 of email verification: user entered their email.

    Validate the email exists, generate a verification code, send it.
    """
    email = update.message.text.strip()
    telegram_id = update.effective_user.id
    telegram_username = update.effective_user.username

    # Basic email validation
    if "@" not in email or "." not in email.split("@")[-1]:
        await update.message.reply_text(
            "❌ That doesn't look like a valid email address.\n\n"
            "Please enter a valid email:",
            parse_mode="Markdown",
        )
        return STATE_WAITING_EMAIL

    try:
        # Step 3: Verify email exists
        user = find_user_by_email(email)
    except EmailNotFoundError:
        await update.message.reply_text(
            "❌ No account was found with that email address.\n\n"
            "Please check the email and try again, or register on the website first.",
            parse_mode="Markdown",
        )
        return STATE_WAITING_EMAIL

    # Check if this Telegram is already linked to a different user
    existing_conn = get_user_by_telegram_id(telegram_id)
    if existing_conn and existing_conn["user_id"] != user["user_id"]:
        await update.message.reply_text(
            "❌ This Telegram account is already linked to a different user.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Step 4: Generate verification code
    # Check if there's already a pending code
    pending = get_pending_verification_code(email, "telegram_link")
    if pending:
        # Reuse the existing code (don't generate a new one to avoid spam)
        # But we need the plain code to send — we only store the hash.
        # So we generate a fresh one instead.
        pass

    code_result = create_verification_code(email, "telegram_link")
    plain_code = code_result["code"]

    # Store email and user_id in context for the next step
    context.user_data["verification_email"] = email
    context.user_data["verification_user_id"] = user["user_id"]

    # Step 5: Send code by email
    first_name = user.get("first_name")
    email_result = send_verification_code(
        email=email,
        code=plain_code,
        purpose="telegram_link",
        first_name=first_name,
    )

    if not email_result.get("success"):
        await update.message.reply_text(
            "❌ Failed to send verification email. Please try again later.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Step 6: Ask user for the code
    await update.message.reply_text(
        build_code_prompt(email),
        parse_mode="Markdown",
    )

    return STATE_WAITING_CODE


async def _handle_code_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """
    Step 7 of email verification: user entered the 6-digit code.

    Validate the code, link Telegram, confirm, auto-retry /signal.
    """
    code = update.message.text.strip()
    telegram_id = update.effective_user.id
    telegram_username = update.effective_user.username

    email = context.user_data.get("verification_email")
    user_id = context.user_data.get("verification_user_id")

    if not email or not user_id:
        await update.message.reply_text(
            "❌ Session expired. Please start again with `/signal MARKET_ID`.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Step 7: Validate the code
    try:
        user = verify_verification_code(
            email=email,
            code=code,
            purpose="telegram_link",
        )
    except VerificationCodeExpiredError:
        await update.message.reply_text(
            "❌ This verification code has expired.\n\n"
            "Please start again with `/signal MARKET_ID`.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END
    except VerificationCodeAttemptsExceededError:
        await update.message.reply_text(
            "❌ Too many failed attempts.\n\n"
            "Please start again with `/signal MARKET_ID`.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END
    except VerificationCodeError:
        await update.message.reply_text(
            "❌ Invalid verification code.\n\n"
            "Please try again or start over with `/signal MARKET_ID`.",
            parse_mode="Markdown",
        )
        return STATE_WAITING_CODE
    except EmailNotFoundError:
        await update.message.reply_text(
            "❌ Account not found. Please start again with `/signal MARKET_ID`.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Step 8: Link the Telegram account
    try:
        link_telegram_to_user(
            user_id=user_id,
            telegram_id=telegram_id,
            telegram_username=telegram_username,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Failed to link Telegram account: {e}\n\n"
            "Please contact support.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Step 9: Confirm to user
    await update.message.reply_text(
        "✅ *Your Telegram account has been successfully linked.*\n\n"
        "You can now use all Telegram commands.",
        parse_mode="Markdown",
    )

    # Step 10: Auto-retry the original /signal command
    pending_m_id = context.user_data.pop("pending_signal_m_id", None)
    context.user_data.pop("verification_email", None)
    context.user_data.pop("verification_user_id", None)

    if pending_m_id:
        await update.message.reply_text(
            f"🔄 Continuing with your original request...\n"
            f"`/signal {pending_m_id}`",
            parse_mode="Markdown",
        )
        # Re-run signal with the stored m_id
        context.args = [str(pending_m_id)]
        await signal(update, context)
    else:
        await update.message.reply_text(
            "You can now use `/signal MARKET_ID` to request analysis.",
            parse_mode="Markdown",
        )

    return ConversationHandler.END


async def _cancel_conversation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Cancel the email verification conversation."""
    context.user_data.pop("pending_signal_m_id", None)
    context.user_data.pop("verification_email", None)
    context.user_data.pop("verification_user_id", None)

    await update.message.reply_text(
        "❌ Linking process cancelled.\n\n"
        "You can start again anytime with `/signal MARKET_ID`.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────
# INTERNAL — Execute signal pipeline
# ─────────────────────────────────────────────────────────────


async def _execute_signal(
    update: Update,
    user: dict,
    market: dict,
    m_id: int,
    signal_req: dict,
    account_type: str,
) -> None:
    """Run the actual AI analysis pipeline for a signal request."""
    telegram_id = update.message.from_user.id
    request_id = signal_req["request_id"]

    await update.message.reply_text(
        f"🔍 *Analysing market `{m_id}`…*\n_{market.get('question', '')}_",
        parse_mode="Markdown",
    )

    # ── Call research API ──
    try:
        resp = requests.post(
            API_URL,
            json={
                "market_id": m_id,
                "query": market.get("question", str(m_id)),
                "deep": True,
                "emit": "json",
            },
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        update_signal_status(request_id, "failed")
        await update.message.reply_text(f"❌ Analysis error: {e}")
        return

    update_signal_status(request_id, "completed")

    # ── Save research ──
    save_market_research(
        m_id=m_id,
        question=market.get("question", ""),
        html_report=data.get("html_report", ""),
        executive_summary=data.get("executive_summary", ""),
        confidence_score=data.get("confidence_score", 0.0),
    )

    # ── Deduct trial or token ──
    trial_notice = ""

    try:
        if account_type == "trial":
            consume_trial(
                user_id=user["user_id"],
            )
            trial_notice = (
                f"\n\n🎁 Trial remaining: "
                f"{user.get('trial_remaining', 0) - 1}"
            )

        else:
            consume_token(
                user_id=user["user_id"],
                amount=1,
                description=f"Signal m_id={m_id}",
            )

    except TrialExpiredError as e:
        update_signal_status(
            request_id,
            "failed_trial",
        )
        await update.message.reply_text(str(e))
        return

    except WalletNotFoundError as e:
        update_signal_status(
            request_id,
            "failed_wallet",
        )
        await update.message.reply_text(str(e))
        return

    except InsufficientTokensError as e:
        update_signal_status(
            request_id,
            "failed_no_tokens",
        )
        await update.message.reply_text(str(e))
        return

    except BusinessError as e:
        update_signal_status(
            request_id,
            "failed",
        )
        await update.message.reply_text(str(e))
        return

    # ── Send Telegram message ──
    summary = data.get("executive_summary", "Analysis complete.")
    tg_msg = (
        f"📊 *Signal ready — Market `{m_id}`*\n"
        f"_{market.get('question', '')}_\n\n"
        f"{summary}"
        f"{trial_notice}"
    )
    await update.message.reply_text(tg_msg, parse_mode="Markdown")
    mark_delivery_sent(request_id, telegram_sent=True)

    # ── Log email for dashboard ──
    user_email = user.get("email", "").strip()
    if user_email:
        from db import log_email
        log_email(
            user_id=user["user_id"],
            recipient_email=user_email,
            email_type="signal",
            subject=f"PolyMarketAlpha Signal — Market {m_id}",
            html_body=data.get("html_report") or f"<p>{summary}</p>",
            related_market_id=m_id,
            related_request_id=request_id,
        )

    print(f"[SIGNAL DONE] request_id={request_id} m_id={m_id}")


# ─────────────────────────────────────────────────────────────
# AUTO-RESUME PENDING SIGNALS
# ─────────────────────────────────────────────────────────────


async def _resume_pending_signals(
    update: Update,
    user: dict,
) -> None:
    """
    Resume any pending signal requests for the user.

    Pending requests have already been validated and created.
    We simply execute them.
    """
    pending = get_pending_signal_requests(user["user_id"])

    if not pending:
        return

    await update.message.reply_text(
        f"⚡ Found {len(pending)} pending signal(s). Processing..."
    )

    for request in pending:
        try:
            result = validate_signal_request(
                user=user,
                m_id=request["m_id"],
            )

            await _execute_signal(
                update=update,
                user=user,
                market=result["market"],
                m_id=request["m_id"],
                signal_req=request,
                account_type=result["account_type"],
            )

        except BusinessError as e:
            update_signal_status(
                request["request_id"],
                "failed",
            )
            await update.message.reply_text(
                f"❌ Unable to process Market {request['m_id']}:\n{str(e)}"
            )

        except Exception as e:
            update_signal_status(
                request["request_id"],
                "failed",
            )
            print(f"[RESUME ERROR] {e}")


# ─────────────────────────────────────────────────────────────
# /set
# ─────────────────────────────────────────────────────────────


async def set_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /set command to update user profile fields.

    Usage: /set FIELD VALUE
    Updates user_id, NOT telegram_id.
    """
    telegram_id = update.effective_user.id
    login = telegram_login(telegram_id)

    if login["status"] == "not_linked":
        await update.message.reply_text(
            build_link_message(login["code"]),
            parse_mode="Markdown",
        )
        return

    user = login["user"]

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "`/set FIELD VALUE`\n\n"
            "Example:\n"
            "`/set first_name John`",
            parse_mode="Markdown",
        )
        return

    field = context.args[0].lower()
    value = " ".join(context.args[1:]).strip()

    db_field = FIELD_MAPPING.get(field)
    if db_field is None:
        await update.message.reply_text("❌ Unknown field.")
        return

    # Email validation
    if db_field == "email":
        if "@" not in value or "." not in value.split("@")[-1]:
            await update.message.reply_text("❌ Invalid email address.")
            return

    # Update via user_id
    from db import update_user_field
    update_user_field(user["user_id"], db_field, value)

    # Refresh user data
    user = get_user_by_id(user["user_id"])

    # Check remaining missing fields
    missing = get_missing_fields(user)
    if missing:
        await update.message.reply_text(
            "✅ Saved.\n\n" + build_missing_message(missing),
            parse_mode="Markdown",
        )
        return

    # Profile now complete
    mark_user_registered(user["user_id"])
    user = get_user_by_id(user["user_id"])

    await update.message.reply_text(
        "✅ Profile updated successfully.",
        parse_mode="Markdown",
    )

    await _resume_pending_signals(update, user)


# ─────────────────────────────────────────────────────────────
# /status
# ─────────────────────────────────────────────────────────────


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /status command.

    Shows profile status, trial remaining, plan, and wallet status.
    """
    telegram_id = update.effective_user.id
    login = telegram_login(telegram_id)

    if login["status"] == "not_linked":
        await update.message.reply_text(
            build_link_message(login["code"]),
            parse_mode="Markdown",
        )
        return

    user = login["user"]

    missing = get_missing_fields(user)
    profile = "✅ Complete" if not missing else f"⚠️ Incomplete ({len(missing)} missing)"

    plan = user.get("account_status", "unknown").upper()
    trial_remaining = user.get("trial_remaining", 0)

    # Build status message
    lines = [
        f"👤 *Account Status*\n",
        f"*Profile:* {profile}",
        f"*Plan:* {plan}",
    ]

    if plan == "TRIAL":
        lines.append(f"*Trial remaining:* {trial_remaining} signals")
    else:
        balance = get_token_balance(user["user_id"])
        lines.append(f"*Token balance:* {balance}")

    if missing:
        lines.append(f"\n*Missing fields:* {', '.join(missing)}")
        lines.append("Use `/set FIELD VALUE` to update.")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────


def main() -> None:
    """Start the Telegram bot."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # ── Conversation handler for email verification linking ──
    email_verification_conv = ConversationHandler(
        entry_points=[
            CommandHandler("signal", signal),
        ],
        states={
            STATE_WAITING_EMAIL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    _handle_email_input,
                ),
            ],
            STATE_WAITING_CODE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    _handle_code_input,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", _cancel_conversation),
        ],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(email_verification_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("set", set_field))
    app.add_handler(CommandHandler("status", status))

    print("🤖 PolyMarketAlphaAI bot running…")
    app.run_polling()


if __name__ == "__main__":
    main()

# ==========================================================
# END OF FILE telegram_bot.py
# ==========================================================
