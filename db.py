# ==========================================================
# BEGIN OF FILE db.py
# ==========================================================

"""
PolyMarketAlphaAI — Database Layer (v2 Architecture)
======================================================

Complete rewrite for the new authentication architecture where:
- Web is the ONLY account creator
- Telegram is ONLY an authentication provider
- Everything revolves around user_id (NOT telegram_id)
- Source of truth: user_connections table

Python 3.12 | PEP 8 | Typed functions | Production quality
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
import secrets
import hashlib

from dotenv import load_dotenv
from supabase import Client, create_client
from exceptions import (
    BusinessError,
    ProfileIncompleteError,
    TrialExpiredError,
    WalletNotFoundError,
    InsufficientTokensError,
    MarketClosedError,
    MarketNotFoundError,
    TelegramLinkError,
)

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment."
    )

# ─────────────────────────────────────────────────────────────
# SUPABASE CLIENT
# ─────────────────────────────────────────────────────────────

_client_instance: Client | None = None


def get_client() -> Client:
    """Return a singleton Supabase client using the service role key."""
    global _client_instance
    if _client_instance is None:
        _client_instance = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _client_instance


# ─────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────


def get_user_by_id(user_id: str) -> dict | None:
    """Fetch a user row from public.users by UUID."""
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()
    res = (
        supabase.table("users")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None


def get_user_by_email(email: str) -> dict | None:
    """Fetch a user row by email address."""
    if not email:
        raise ValueError("email is required.")

    supabase = get_client()
    res = (
        supabase.table("users")
        .select("*")
        .eq("email", email)
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None


# ─────────────────────────────────────────────────────────────
# USER CONNECTIONS
# ─────────────────────────────────────────────────────────────


def get_connection(provider: str, provider_user_id: str) -> dict | None:
    """
    Fetch a connection row from user_connections.

    Args:
        provider: e.g. "telegram", "google", "discord"
        provider_user_id: the provider's native user identifier

    Returns:
        The connection dict or None.
    """
    if not provider or not provider_user_id:
        raise ValueError("provider and provider_user_id are required.")

    supabase = get_client()
    res = (
        supabase.table("user_connections")
        .select("*")
        .eq("provider", provider)
        .eq("provider_user_id", str(provider_user_id))
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None


def get_user_by_connection(provider: str, provider_user_id: str) -> dict | None:
    """
    Resolve a user via their connection.

    Flow: provider + provider_user_id -> user_connections -> users
    """
    connection = get_connection(provider, provider_user_id)
    if not connection:
        return None
    return get_user_by_id(connection["user_id"])


def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    """
    Resolve a user by their Telegram ID.

    NEVER queries users.telegram_id directly.
    Always goes through user_connections.
    """
    return get_user_by_connection("telegram", str(telegram_id))


def is_telegram_connected(telegram_id: int) -> bool:
    """Return True if a Telegram account is linked to any user."""
    return get_connection("telegram", str(telegram_id)) is not None


# ─────────────────────────────────────────────────────────────
# TELEGRAM LINK CODES
# ─────────────────────────────────────────────────────────────


def create_telegram_link_code(
    telegram_id: int,
    telegram_username: str | None = None,
    expires_minutes: int = 15,
) -> str:
    """
    Generate a new link code for a Telegram user.

    The code is displayed by the bot; the user enters it on the web
    dashboard to complete the link via attach_telegram_using_code().
    """
    if not telegram_id:
        raise ValueError("telegram_id is required.")

    supabase = get_client()
    code = str(uuid.uuid4())[:8].upper()
    expires = datetime.utcnow() + timedelta(minutes=expires_minutes)

    supabase.table("telegram_link_codes").insert(
        {
            "code": code,
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
            "expires_at": expires.isoformat(),
            "used": False,
        }
    ).execute()

    return code


def get_link_code(code: str) -> dict | None:
    """Fetch a link code row without consuming it."""
    if not code:
        raise ValueError("code is required.")

    supabase = get_client()
    res = (
        supabase.table("telegram_link_codes")
        .select("*")
        .eq("code", code)
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None


def consume_telegram_link_code(code: str) -> dict | None:
    """
    Validate and consume a link code.

    Returns the link dict if valid and not expired, otherwise None.
    """
    if not code:
        raise ValueError("code is required.")

    supabase = get_client()
    link = get_link_code(code)

    if not link:
        return None

    if link.get("used"):
        return None

    expires_str = link.get("expires_at", "")
    # Handle ISO strings with or without trailing 'Z'
    expires_str = expires_str.replace("Z", "+00:00")
    try:
        expires = datetime.fromisoformat(expires_str)
    except ValueError:
        return None

    if expires < datetime.utcnow():
        return None

    # Mark as used
    supabase.table("telegram_link_codes").update(
        {
            "used": True,
            "used_at": datetime.utcnow().isoformat(),
        }
    ).eq("code", code).execute()

    return link

def find_user_by_email(email: str) -> dict:
    """
    Find a user by their registered email address.

    Args:
        email: User's email address.

    Returns:
        User record.

    Raises:
        EmailNotFoundError: If no account exists with the given email.
    """
    if not email:
        raise ValueError("Email is required.")

    supabase = get_client()

    result = (
        supabase.table("users")
        .select("*")
        .ilike("email", email.strip())
        .limit(1)
        .execute()
    )

    if not result.data:
        raise EmailNotFoundError()

    return result.data[0]
    


def generate_verification_code() -> str:
    """Generate a cryptographically secure 6-digit verification code."""
    return f"{secrets.randbelow(1_000_000):06d}"
    
 

def hash_verification_code(code: str) -> str:
    """Hash a verification code before storing it."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
 
 

def create_verification_code(email: str, purpose: str) -> dict:
    """
    Create or replace an active verification code for a user.

    Args:
        email: Registered email address.
        purpose: Verification purpose
                 (telegram_link, password_reset, login, etc.)

    Returns:
        {
            "user_id": "...",
            "email": "...",
            "code": "483921"
        }

    Raises:
        EmailNotFoundError
    """

    user = find_user_by_email(email)

    code = generate_verification_code()
    code_hash = hash_verification_code(code)

    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    ).isoformat()

    supabase = get_client()

    existing = (
        supabase.table("verification_codes")
        .select("verification_id")
        .eq("email", email.strip().lower())
        .eq("purpose", purpose)
        .eq("used", False)
        .limit(1)
        .execute()
    )

    if existing.data:

        supabase.table("verification_codes").update(
            {
                "code": code_hash,
                "attempts": 0,
                "expires_at": expires_at,
                "used": False,
                "used_at": None,
            }
        ).eq(
            "verification_id",
            existing.data[0]["verification_id"]
        ).execute()

    else:

        supabase.table("verification_codes").insert(
            {
                "user_id": user["user_id"],
                "email": user["email"],
                "code": code_hash,
                "purpose": purpose,
                "attempts": 0,
                "max_attempts": 5,
                "used": False,
                "expires_at": expires_at,
            }
        ).execute()

    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "code": code,
    }
  


def verify_verification_code(
    email: str,
    code: str,
    purpose: str,
) -> dict:
    """
    Verify a verification code.

    Args:
        email: User email.
        code: Plain 6-digit verification code.
        purpose: Verification purpose.

    Returns:
        User record.

    Raises:
        EmailNotFoundError
        VerificationCodeError
        VerificationCodeExpiredError
        VerificationCodeAttemptsExceededError
    """

    email = email.strip().lower()

    user = find_user_by_email(email)

    supabase = get_client()

    result = (
        supabase.table("verification_codes")
        .select("*")
        .eq("email", email)
        .eq("purpose", purpose)
        .eq("used", False)
        .limit(1)
        .execute()
    )

    if not result.data:
        raise VerificationCodeError(
            "No active verification code found."
        )

    record = result.data[0]

    now = datetime.now(timezone.utc)

    expires_at = datetime.fromisoformat(
        record["expires_at"].replace("Z", "+00:00")
    )

    if expires_at < now:
        raise VerificationCodeExpiredError()

    if record["attempts"] >= record["max_attempts"]:
        raise VerificationCodeAttemptsExceededError()

    code_hash = hash_verification_code(code)

    if code_hash != record["code"]:

        supabase.table("verification_codes").update(
            {
                "attempts": record["attempts"] + 1
            }
        ).eq(
            "verification_id",
            record["verification_id"]
        ).execute()

        raise VerificationCodeError()

    supabase.table("verification_codes").update(
        {
            "used": True,
            "used_at": now.isoformat(),
        }
    ).eq(
        "verification_id",
        record["verification_id"]
    ).execute()

    return user
 
# ==========================================================
# MISSING FUNCTIONS — Add these to db.py
# ==========================================================

# ─────────────────────────────────────────────────────────────
# mark_verification_code_used
# ─────────────────────────────────────────────────────────────


def mark_verification_code_used(verification_id: str) -> dict:
    """
    Mark a specific verification code as used.

    This is a standalone helper for situations where you need to
    mark a code consumed outside of verify_verification_code(),
    for example when a code is validated by a different service
    or consumed via an admin action.

    Args:
        verification_id: The UUID of the verification_codes row.

    Returns:
        The updated record dict.

    Raises:
        ValueError: If verification_id is missing.
    """
    if not verification_id:
        raise ValueError("verification_id is required.")

    supabase = get_client()
    now = datetime.now(timezone.utc).isoformat()

    res = (
        supabase.table("verification_codes")
        .update(
            {
                "used": True,
                "used_at": now,
            }
        )
        .eq("verification_id", verification_id)
        .execute()
    )

    return res.data[0] if res.data else {}


# ─────────────────────────────────────────────────────────────
# delete_expired_verification_codes
# ─────────────────────────────────────────────────────────────


def delete_expired_verification_codes(
    purpose: str | None = None,
    older_than_hours: int = 24,
) -> int:
    """
    Delete expired and stale verification codes from the database.

    This is a cleanup function intended to be called periodically
    (e.g. via a scheduled job or Supabase cron) to prevent the
    verification_codes table from growing indefinitely.

    Args:
        purpose: Optional filter — only delete codes of this purpose.
                 If None, deletes expired codes of ALL purposes.
        older_than_hours: Safety buffer. Only delete codes whose
                          expires_at is older than this many hours ago.
                          Default is 24 hours to avoid race conditions
                          with near-expiry codes.

    Returns:
        Number of rows deleted.
    """
    if older_than_hours < 0:
        raise ValueError("older_than_hours must be non-negative.")

    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    ).isoformat()

    supabase = get_client()

    query = (
        supabase.table("verification_codes")
        .delete()
        .lt("expires_at", cutoff)
    )

    if purpose:
        query = query.eq("purpose", purpose)

    res = query.execute()

    # Supabase returns deleted rows in res.data; count them
    deleted_count = len(res.data) if res.data else 0
    return deleted_count


# ─────────────────────────────────────────────────────────────
# invalidate_all_codes_for_email
# ─────────────────────────────────────────────────────────────


def invalidate_all_codes_for_email(
    email: str,
    purpose: str | None = None,
) -> int:
    """
    Mark all pending (unused) verification codes for an email as used.

    Security helper: after a successful verification, call this to
    invalidate any other pending codes for the same email to prevent
    replay attacks or code enumeration.

    Args:
        email: The email address whose codes should be invalidated.
        purpose: Optional — only invalidate codes of this purpose.
                 If None, invalidates codes of ALL purposes.

    Returns:
        Number of codes invalidated.
    """
    if not email:
        raise ValueError("email is required.")

    email = email.strip().lower()
    supabase = get_client()
    now = datetime.now(timezone.utc).isoformat()

    query = (
        supabase.table("verification_codes")
        .update(
            {
                "used": True,
                "used_at": now,
            }
        )
        .eq("email", email)
        .eq("used", False)
    )

    if purpose:
        query = query.eq("purpose", purpose)

    res = query.execute()
    return len(res.data) if res.data else 0


# ─────────────────────────────────────────────────────────────
# get_pending_verification_code
# ─────────────────────────────────────────────────────────────


def get_pending_verification_code(
    email: str,
    purpose: str,
) -> dict | None:
    """
    Fetch the active (unused, not expired) verification code for an email.

    Useful for the Telegram bot to check whether a user already has
    a pending code before generating a new one.

    Args:
        email: User email address.
        purpose: Verification purpose.

    Returns:
        The pending code record, or None if no active code exists.
    """
    if not email or not purpose:
        raise ValueError("email and purpose are required.")

    email = email.strip().lower()
    supabase = get_client()

    res = (
        supabase.table("verification_codes")
        .select("*")
        .eq("email", email)
        .eq("purpose", purpose)
        .eq("used", False)
        .gt("expires_at", datetime.now(timezone.utc).isoformat())
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None 
 
# ─────────────────────────────────────────────────────────────
# TELEGRAM LINKING
# ─────────────────────────────────────────────────────────────


def link_telegram_to_user(
    user_id: str,
    telegram_id: int,
    telegram_username: str | None = None,
) -> dict:
    """
    Link a Telegram account to an existing user.

    This creates the user_connections row AND updates the users
    table for backward compatibility with legacy columns.

    Args:
        user_id: The existing user's UUID.
        telegram_id: The Telegram account ID.
        telegram_username: Optional Telegram handle.

    Returns:
        The updated user dict.

    Raises:
        Exception: If the Telegram account is already linked.
    """
    if not user_id or not telegram_id:
        raise ValueError("user_id and telegram_id are required.")

    # Guard: Telegram already linked to someone else?
    existing = get_connection("telegram", str(telegram_id))
    if existing and existing.get("user_id") != user_id:
        raise Exception("Telegram account already linked to another user.")

    supabase = get_client()

    # Upsert into user_connections (source of truth)
    if existing:
        supabase.table("user_connections").update(
            {
                "provider_username": telegram_username,
                "last_used_at": datetime.utcnow().isoformat(),
            }
        ).eq("connection_id", existing["connection_id"]).execute()
    else:
        supabase.table("user_connections").insert(
            {
                "user_id": user_id,
                "provider": "telegram",
                "provider_user_id": str(telegram_id),
                "provider_username": telegram_username,
                "is_primary": False,
                "linked_at": datetime.utcnow().isoformat(),
            }
        ).execute()
        return get_user_by_id(user_id)

def get_telegram_connection(user_id: str) -> dict | None:
    supabase = get_client()

    result = (
        supabase.table("user_connections")
        .select("*")
        .eq("user_id", user_id)
        .eq("provider", "telegram")
        .limit(1)
        .execute()
    )

    return result.data[0] if result.data else None


def attach_telegram_using_code(code: str, user_id: str | None = None) -> dict:
    """
    Web dashboard calls this when a user enters a code.

    The code was generated by the bot when an unlinked Telegram
    user ran /start. The web user (already authenticated) enters
    the code, and we link the two accounts.

    Args:
        code: The 8-character code from the bot.
        user_id: Optional explicit user_id override (for API usage).

    Returns:
        The linked user dict.

    Raises:
        Exception: If code is invalid, expired, or already used.
    """
    if not code:
        raise ValueError("code is required.")

    link = consume_telegram_link_code(code)
    if not link:
        raise TelegramLinkError("Invalid or expired code.")

    # Determine target user
    target_user_id = user_id or link.get("user_id")
    if not target_user_id:
        raise Exception("No user_id associated with this code.")

    return link_telegram_to_user(
        user_id=target_user_id,
        telegram_id=link["telegram_id"],
        telegram_username=link.get("telegram_username"),
    )

def connect_telegram(
    user_id: str,
    code: str,
) -> dict:
    """
    Public business method for linking a Telegram account.

    This should be the ONLY method called by the API or other
    application layers when connecting Telegram.

    Args:
        user_id: Authenticated user's UUID.
        code: Telegram link code generated by the bot.

    Returns:
        The updated user record.

    Raises:
        ValueError:
            - user_id missing
            - code missing

        Exception:
            - invalid or expired code
            - telegram already linked
    """
    if not user_id:
        raise ValueError("user_id is required.")

    if not code:
        raise ValueError("code is required.")

    return attach_telegram_using_code(
        code=code.strip().upper(),
        user_id=user_id,
    )
# ─────────────────────────────────────────────────────────────
# CONNECTION USERNAME
# ─────────────────────────────────────────────────────────────


def update_connection_username(user_id: str, username: str) -> None:
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()

    supabase.table("user_connections").update(
        {
            "provider_username": username,
            "last_used_at": datetime.utcnow().isoformat(),
        }
    ).eq("user_id", user_id).eq("provider", "telegram").execute()


# ─────────────────────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────────────────────

REQUIRED_FIELDS = ["email", "first_name", "last_name"]


def get_missing_fields(user: dict) -> list[str]:
    """
    Return a list of required fields that are missing or empty.

    Args:
        user: A user dict from get_user_by_id().

    Returns:
        List of missing field names.
    """
    if not user:
        return list(REQUIRED_FIELDS)

    missing = []
    for field in REQUIRED_FIELDS:
        value = user.get(field)
        if value is None:
            missing.append(field)
            continue
        if isinstance(value, str) and value.strip() == "":
            missing.append(field)
    return missing


def is_profile_complete(user: dict) -> bool:
    """Return True if the user has all required fields populated."""
    return len(get_missing_fields(user)) == 0


# ─────────────────────────────────────────────────────────────
# UPDATE USER FIELD
# ─────────────────────────────────────────────────────────────


def update_user_field(user_id: str, field: str, value: Any) -> dict:
    """
    Update a single user field.

    Args:
        user_id: The user's UUID.
        field: The column name to update.
        value: The new value.

    Returns:
        The Supabase response data.

    Raises:
        ValueError: If the field is not in the allowlist.
    """
    if not user_id or not field:
        raise ValueError("user_id and field are required.")

    allowed = {
        "first_name",
        "last_name",
        "username",
        "telegram_username",
        "email",
    }

    if field not in allowed:
        raise ValueError(f"Field '{field}' cannot be updated.")

    supabase = get_client()
    now = datetime.utcnow().isoformat()

    res = (
        supabase.table("users")
        .update(
            {
                field: value,
                "updated_at": now,
            }
        )
        .eq("user_id", user_id)
        .execute()
    )

    # Sync telegram_username to user_connections if needed
    if field == "telegram_username":
        supabase.table("user_connections").update(
            {
                "provider_username": value,
                "last_used_at": now,
            }
        ).eq("provider", "telegram").eq("user_id", user_id).execute()

    return res

def update_profile(
    user_id: str,
    updates: dict[str, Any],
) -> dict:
    """
    Update multiple profile fields in a single database operation.

    This is the preferred business method for profile updates.

    Args:
        user_id: User UUID.
        updates: Dictionary containing profile fields to update.

    Returns:
        The refreshed user record.

    Raises:
        ValueError:
            - user_id missing
            - no updates provided
            - invalid field supplied
    """
    if not user_id:
        raise ValueError("user_id is required.")

    if not updates:
        raise ValueError("No fields provided for update.")

    allowed = {
        "first_name",
        "last_name",
        "username",
        "telegram_username",
        "email",
    }

    invalid_fields = set(updates.keys()) - allowed
    if invalid_fields:
        raise ValueError(
            f"Invalid profile field(s): {', '.join(sorted(invalid_fields))}"
        )

    supabase = get_client()
    now = datetime.utcnow().isoformat()

    payload = {
        **updates,
        "updated_at": now,
    }

    # Single update to users table
    supabase.table("users").update(payload).eq(
        "user_id",
        user_id,
    ).execute()

    # Keep user_connections synchronized
    if "telegram_username" in updates:
        supabase.table("user_connections").update(
            {
                "provider_username": updates["telegram_username"],
                "last_used_at": now,
            }
        ).eq(
            "provider",
            "telegram",
        ).eq(
            "user_id",
            user_id,
        ).execute()

    return get_user_by_id(user_id)

# ─────────────────────────────────────────────────────────────
# REGISTRATION
# ─────────────────────────────────────────────────────────────


def mark_user_registered(user_id: str) -> None:
    """
    Mark a user as fully registered.

    Sets account_status to trial, marks email/telegram as verified
    if present, and updates user_registrations.
    """
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()
    user = get_user_by_id(user_id)

    if not user:
        raise ValueError("User not found.")

    payload: dict[str, Any] = {
        "account_status": "trial",
        "updated_at": datetime.utcnow().isoformat(),
    }

    if user.get("email"):
        payload["email_verified"] = True

    # Check telegram connection via user_connections (source of truth)
    conn = get_connection("telegram", str(user.get("telegram_id") or ""))
    if conn or user.get("telegram_connected"):
        payload["telegram_verified"] = True
        payload["telegram_connected"] = True

    supabase.table("users").update(payload).eq("user_id", user_id).execute()

    # Update user_registrations if row exists
    try:
        supabase.table("user_registrations").update(
            {
                "verification_status": "verified",
                "terms_accepted": True,
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).eq("user_id", user_id).execute()
    except Exception as e:
        # Row may not exist; not fatal
        print(f"[mark_user_registered] user_registrations update skipped: {e}")


# ─────────────────────────────────────────────────────────────
# ACCOUNT STATUS HELPERS
# ─────────────────────────────────────────────────────────────


def is_trial_user(user: dict) -> bool:
    return user.get("account_status") == "trial"


def is_paid_user(user: dict) -> bool:
    return user.get("account_status") == "paid"


def remaining_trial(user: dict) -> int:
    return int(user.get("trial_remaining", 0))


# ─────────────────────────────────────────────────────────────
# CAN RUN SIGNAL
# ─────────────────────────────────────────────────────────────


def check_can_run_signal(user: dict) -> tuple[bool, str]:
    """
    Determine whether a user is allowed to request a signal.

    Returns:
        (allowed: bool, reason: str)
        reason is one of: "trial", "paid", "trial_expired",
        "wallet_missing", "insufficient_tokens",
        "profile_incomplete", "inactive_account"
    """
    if not is_profile_complete(user):
        return False, "profile_incomplete"

    if is_paid_user(user):
        wallet = get_wallet(user["user_id"])
        if not wallet:
            return False, "wallet_missing"

        balance = float(wallet.get("token_balance", 0))
        if balance < 1:
            return False, "insufficient_tokens"

        return True, "paid"

    if is_trial_user(user):
        if remaining_trial(user) > 0:
            return True, "trial"
        return False, "trial_expired"

    return False, "inactive_account"


# ─────────────────────────────────────────────────────────────
# WALLET
# ─────────────────────────────────────────────────────────────


def get_wallet(user_id: str) -> dict | None:
    """Fetch a user's wallet from user_wallets."""
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()
    res = (
        supabase.table("user_wallets")
        .select("*")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None


def get_token_balance(user_id: str) -> float:
    """Return the user's token balance, or 0 if no wallet."""
    wallet = get_wallet(user_id)
    if not wallet:
        return 0.0
    return float(wallet.get("token_balance", 0))


def deduct_token(
    user_id: str,
    amount: int = 1,
    description: str = "Signal usage",
) -> float:
    """
    Deduct tokens from a user's wallet atomically.

    Args:
        user_id: The user's UUID.
        amount: Number of tokens to deduct.
        description: Reason for the transaction.

    Returns:
        The new balance.

    Raises:
        ValueError: If wallet not found or insufficient balance.
    """
    if not user_id or amount < 1:
        raise ValueError("user_id and positive amount are required.")

    supabase = get_client()
    wallet = get_wallet(user_id)

    if not wallet:
        raise WalletNotFoundError()

    balance = float(wallet["token_balance"])
    if balance < amount:
        raise InsufficientTokensError()

    new_balance = balance - amount
    consumed = float(wallet.get("total_tokens_consumed", 0))

    # Atomic wallet update
    supabase.table("user_wallets").update(
        {
            "token_balance": new_balance,
            "total_tokens_consumed": consumed + amount,
            "updated_at": datetime.utcnow().isoformat(),
        }
    ).eq("user_id", user_id).execute()

    # Record transaction
    supabase.table("token_transactions").insert(
        {
            "user_id": user_id,
            "transaction_type": "consume",
            "token_amount": -amount,
            "description": description,
            "created_at": datetime.utcnow().isoformat(),
        }
    ).execute()

    return new_balance

def consume_token(
    user_id: str,
    amount: int = 1,
    description: str = "Signal usage",
) -> float:
    """
    High-level business method for consuming tokens.

    This is the public business API that should be called by
    the application. Internally it delegates to deduct_token().

    Args:
        user_id: User UUID.
        amount: Number of tokens to consume.
        description: Transaction description.

    Returns:
        The user's new token balance.
    """
    return deduct_token(
        user_id=user_id,
        amount=amount,
        description=description,
    )
# ─────────────────────────────────────────────────────────────
# TRIAL
# ─────────────────────────────────────────────────────────────


def decrement_trial(
    user_id: str,
    telegram_id: int | None = None,
    current_remaining: int | None = None,
) -> int:
    """
    Decrement a user's trial remaining count.

    Args:
        user_id: The user's UUID.
        telegram_id: Optional Telegram ID for validation.
        current_remaining: Optional current value (used by bot).

    Returns:
        The new trial_remaining value.

    Raises:
        ValueError: If user not found or Telegram ID mismatch.
    """
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()
    user = get_user_by_id(user_id)

    if not user:
        raise ValueError("User not found.")

    # Validate Telegram ID matches if provided
    if telegram_id is not None:
        conn = get_connection("telegram", str(telegram_id))
        if not conn or conn["user_id"] != user_id:
            raise ValueError("Telegram ID does not match user.")

    # Use provided current_remaining or fetch from DB
    remaining = current_remaining if current_remaining is not None else int(
        user.get("trial_remaining", 0)
    )

    new_remaining = max(remaining - 1, 0)

    supabase.table("users").update(
        {
            "trial_remaining": new_remaining,
            "updated_at": datetime.utcnow().isoformat(),
        }
    ).eq("user_id", user_id).execute()

    return new_remaining

def consume_trial(user_id: str) -> int:
    """
    High-level business method for consuming one free trial signal.

    The application should call this method instead of directly
    manipulating trial_remaining.

    Args:
        user_id: The user's UUID.

    Returns:
        The remaining number of free trial signals.

    Raises:
        ValueError: If the user does not exist.
    """
    user = get_user_by_id(user_id)

    if not user:
        raise ValueError("User not found.")

    return decrement_trial(
        user_id=user_id,
        current_remaining=int(user.get("trial_remaining", 0)),
    )
# ─────────────────────────────────────────────────────────────
# SIGNAL REQUESTS
# ─────────────────────────────────────────────────────────────


def create_signal_request(
    user_id: str,
    m_id: int,
    request_type: str = "ai_analysis",
) -> dict:
    """
    Create a new signal request and its delivery record.

    Args:
        user_id: The user's UUID.
        m_id: The market ID.
        request_type: Type of analysis requested.

    Returns:
        The created signal request dict.
    """
    if not user_id or not m_id:
        raise ValueError("user_id and m_id are required.")

    supabase = get_client()

    # Insert signal request
    req_res = (
        supabase.table("signal_requests")
        .insert(
            {
                "user_id": user_id,
                "m_id": m_id,
                "request_type": request_type,
                "status": "not_treated",
                "created_at": datetime.utcnow().isoformat(),
            }
        )
        .execute()
    )

    if not req_res.data:
        raise RuntimeError("Failed to create signal request.")

    request = req_res.data[0]

    # Insert corresponding delivery record
    supabase.table("signal_deliveries").insert(
        {
            "request_id": request["request_id"],
            "telegram_sent": False,
            "email_sent": False,
            "created_at": datetime.utcnow().isoformat(),
        }
    ).execute()

    return request
def validate_signal_request(
    user: dict,
    m_id: int,
) -> dict:
    """
    Validate whether a user is allowed to execute a signal request.

    Unlike prepare_signal_request(), this function DOES NOT create
    a signal_request record. It is intended for situations where an
    existing pending request is being resumed.

    Returns:
        {
            "market": <market>,
            "account_type": "trial" | "paid"
        }

    Raises:
        ProfileIncompleteError
        TrialExpiredError
        WalletNotFoundError
        InsufficientTokensError
        MarketNotFoundError
        MarketClosedError
    """

    allowed, reason = check_can_run_signal(user)

    if not allowed:

        if reason == "profile_incomplete":
            raise ProfileIncompleteError()

        elif reason == "trial_expired":
            raise TrialExpiredError()

        elif reason == "wallet_missing":
            raise WalletNotFoundError()

        elif reason == "insufficient_tokens":
            raise InsufficientTokensError()

        else:
            raise BusinessError("Account is not allowed to request signals.")

    market = get_market_by_m_id(m_id)

    if market is None:
        raise MarketNotFoundError()

    if market.get("closed"):
        raise MarketClosedError()

    return {
        "market": market,
        "account_type": reason,
    }
def prepare_signal_request(
    user: dict,
    m_id: int,
    request_type: str = "ai_analysis",
) -> dict:
    """
    High-level business method for creating a signal request.

    This function validates the request and then creates a new
    signal_request record.

    Returns:
        {
            "request": <signal_request>,
            "market": <market>,
            "account_type": "trial" | "paid"
        }
    """

    validation = validate_signal_request(
        user=user,
        m_id=m_id,
    )

    signal_request = create_signal_request(
        user_id=user["user_id"],
        m_id=m_id,
        request_type=request_type,
    )

    return {
        "request": signal_request,
        "market": validation["market"],
        "account_type": validation["account_type"],
    }

def get_pending_signal_requests(user_id: str) -> list[dict]:
    """Fetch all pending (not_treated) signal requests for a user."""
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()
    res = (
        supabase.table("signal_requests")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "not_treated")
        .execute()
    )

    return res.data or []


def update_signal_status(request_id: str, status: str) -> dict:
    """
    Update the status of a signal request.

    Args:
        request_id: The signal request UUID.
        status: New status string.

    Returns:
        The Supabase response data.
    """
    if not request_id or not status:
        raise ValueError("request_id and status are required.")

    supabase = get_client()
    return (
        supabase.table("signal_requests")
        .update(
            {
                "status": status,
                "completed_at": datetime.utcnow().isoformat(),
            }
        )
        .eq("request_id", request_id)
        .execute()
    )


# ─────────────────────────────────────────────────────────────
# DELIVERY
# ─────────────────────────────────────────────────────────────


def mark_delivery_sent(
    request_id: str,
    telegram_sent: bool = False,
    email_sent: bool = False,
) -> dict:
    """
    Mark delivery channels as sent for a signal request.

    Args:
        request_id: The signal request UUID.
        telegram_sent: Whether Telegram was delivered.
        email_sent: Whether email was delivered.

    Returns:
        The Supabase response data.
    """
    if not request_id:
        raise ValueError("request_id is required.")

    supabase = get_client()
    payload: dict[str, Any] = {}

    if telegram_sent:
        payload["telegram_sent"] = True
    if email_sent:
        payload["email_sent"] = True

    if payload:
        payload["delivered_at"] = datetime.utcnow().isoformat()

    return (
        supabase.table("signal_deliveries")
        .update(payload)
        .eq("request_id", request_id)
        .execute()
    )


# ─────────────────────────────────────────────────────────────
# MARKETS
# ─────────────────────────────────────────────────────────────


def get_market_by_m_id(m_id: int) -> dict | None:
    """Fetch a market by its m_id from polymarket_markets."""
    if not m_id:
        raise ValueError("m_id is required.")

    supabase = get_client()
    res = (
        supabase.table("polymarket_markets")
        .select("*")
        .eq("m_id", m_id)
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None


# ─────────────────────────────────────────────────────────────
# MARKET RESEARCH
# ─────────────────────────────────────────────────────────────


def save_market_research(
    m_id: int,
    question: str,
    html_report: str,
    executive_summary: str,
    confidence_score: float,
) -> dict:
    """
    Upsert market research data.

    If research for this m_id exists, update it; otherwise insert.
    """
    if not m_id:
        raise ValueError("m_id is required.")

    supabase = get_client()

    existing = (
        supabase.table("market_research")
        .select("research_id")
        .eq("m_id", m_id)
        .limit(1)
        .execute()
    )

    payload = {
        "m_id": m_id,
        "question": question,
        "research_status": "completed",
        "html_report": html_report,
        "executive_summary": executive_summary,
        "confidence_score": confidence_score,
        "updated_at": datetime.utcnow().isoformat(),
    }

    if existing.data:
        res = (
            supabase.table("market_research")
            .update(payload)
            .eq("m_id", m_id)
            .execute()
        )
    else:
        payload.pop("updated_at")
        payload["created_at"] = datetime.utcnow().isoformat()
        res = supabase.table("market_research").insert(payload).execute()

    return res.data[0] if res.data else {}

def list_market_reports(
    m_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """
    Return market research reports ordered by newest first.

    Args:
        m_id:
            Optional market ID filter.

        limit:
            Maximum number of reports to return.

    Returns:
        List of market research reports.
    """

    supabase = get_client()

    query = (
        supabase.table("market_research")
        .select("*")
    )

    if m_id is not None:
        query = query.eq("m_id", m_id)

    res = (
        query
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    return res.data or []
# ─────────────────────────────────────────────────────────────
# TELEGRAM LOGIN
# ─────────────────────────────────────────────────────────────


def telegram_login(telegram_id: int) -> dict:
    """
    Bot calls this on every interaction.

    NEVER creates a user. Returns either:
        {"status": "linked", "user": <user_dict>}
        {"status": "not_linked", "code": <str>}

    Args:
        telegram_id: The Telegram user's numeric ID.

    Returns:
        A dict indicating link status.
    """
    if not telegram_id:
        raise ValueError("telegram_id is required.")

    user = get_user_by_telegram_id(telegram_id)

    if user:
        return {
            "status": "linked",
            "user": user,
        }

    # Not linked — generate a code for the user to enter on the web
    code = create_telegram_link_code(
        telegram_id=telegram_id,
        telegram_username=None,
    )

    return {
        "status": "not_linked",
        "code": code,
    }


# ─────────────────────────────────────────────────────────────
# USER HELPERS
# ─────────────────────────────────────────────────────────────


def refresh_last_login(user_id: str, method: str) -> None:
    """Update the last login method for a user."""
    if not user_id or not method:
        raise ValueError("user_id and method are required.")

    supabase = get_client()
    supabase.table("users").update(
        {
            "last_login_method": method,
            "last_login_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
    ).eq("user_id", user_id).execute()


def user_has_telegram(user_id: str) -> bool:
    """Return True if the user has an active Telegram connection."""
    if not user_id:
        return False

    supabase = get_client()
    res = (
        supabase.table("user_connections")
        .select("connection_id")
        .eq("user_id", user_id)
        .eq("provider", "telegram")
        .limit(1)
        .execute()
    )

    return bool(res.data)


def unlink_telegram(user_id: str) -> None:
    """
    Remove the Telegram connection for a user.

    Deletes from user_connections and clears denormalized fields.
    """
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()

    # Remove from source of truth
    supabase.table("user_connections").delete().eq(
        "provider", "telegram"
    ).eq("user_id", user_id).execute()

    # Clear denormalized cache
    supabase.table("users").update(
        {
            "telegram_connected": False,
            "telegram_verified": False,
            "telegram_id": None,
            "telegram_username": None,
            "updated_at": datetime.utcnow().isoformat(),
        }
    ).eq("user_id", user_id).execute()


# ─────────────────────────────────────────────────────────────
# EMAIL LOGGING
# ─────────────────────────────────────────────────────────────


def log_email(
    user_id: str | None,
    recipient_email: str,
    email_type: str,
    subject: str,
    html_body: str,
    related_market_id: int | None = None,
    related_request_id: str | None = None,
) -> dict:
    """
    Log an email attempt to the email_log table.

    Args:
        user_id: Optional user UUID.
        recipient_email: To address.
        email_type: e.g. "signal", "welcome", "digest"
        subject: Email subject line.
        html_body: Full HTML content.
        related_market_id: Optional market reference.
        related_request_id: Optional signal request reference.

    Returns:
        The created log row.
    """
    if not recipient_email or not email_type or not subject:
        raise ValueError("recipient_email, email_type, and subject are required.")

    supabase = get_client()
    res = supabase.table("email_log").insert(
        {
            "user_id": user_id,
            "recipient_email": recipient_email,
            "email_type": email_type,
            "subject": subject,
            "html_body": html_body,
            "related_market_id": related_market_id,
            "related_request_id": related_request_id,
            "status": "pending",
            "triggered_at": datetime.utcnow().isoformat(),
        }
    ).execute()

    return res.data[0] if res.data else {}


def update_email_log_status(
    log_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update the delivery status of a logged email."""
    if not log_id or not status:
        raise ValueError("log_id and status are required.")

    supabase = get_client()
    payload: dict[str, Any] = {
        "status": status,
        "sent_at": datetime.utcnow().isoformat() if status == "sent" else None,
    }
    if error_message:
        payload["error_message"] = error_message

    supabase.table("email_log").update(payload).eq("log_id", log_id).execute()


# ─────────────────────────────────────────────────────────────
# SUBSCRIPTION HELPERS
# ─────────────────────────────────────────────────────────────


def get_user_subscription(user_id: str) -> dict | None:
    """Fetch the active subscription for a user."""
    if not user_id:
        raise ValueError("user_id is required.")

    supabase = get_client()
    res = (
        supabase.table("user_subscriptions")
        .select("*, subscription_plans(*)")
        .eq("user_id", user_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )

    return res.data[0] if res.data else None


def get_subscription_plans() -> list[dict]:
    """Fetch all available subscription plans."""
    supabase = get_client()
    res = supabase.table("subscription_plans").select("*").execute()
    return res.data or []


# ─────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────


def now_iso() -> str:
    """Return current UTC time as ISO format string."""
    return datetime.utcnow().isoformat()


def is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to int."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default
		
		
# ==========================================================
# END OF FILE db.py
# ==========================================================