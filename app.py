
# ==========================================================
# BEGIN OF FILE app.py
# ==========================================================

"""
PolyMarketAlphaAI — Backend API (v2 Architecture)
==================================================

FastAPI backend exposing REST endpoints for the web dashboard.

Key endpoints:
    POST /api/connect-telegram    — Link Telegram via code
    GET  /api/me                  — Get current user data
    POST /api/profile             — Update profile fields
    GET  /api/wallet              — Get wallet info
    GET  /api/signals             — Get user's signal history
    POST /api/signals             — Create a new signal request
    GET  /api/reports             — Get market research reports

Python 3.12 | FastAPI | Typed | Production quality
"""

import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from db import (
    check_can_run_signal,
    connect_telegram,
    consume_token,
    consume_trial,
    create_signal_request,
    list_market_reports,
    get_market_by_m_id,
    get_missing_fields,
    get_token_balance,
    get_user_by_id,
    get_user_subscription,
    get_wallet,
    list_signal_requests,
    is_profile_complete,
    prepare_signal_request,
    unlink_telegram,
    update_profile,
)
from exceptions import (
    BusinessError,
    ProfileIncompleteError,
    TrialExpiredError,
    WalletNotFoundError,
    InsufficientTokensError,
    MarketNotFoundError,
    MarketClosedError,
    TelegramLinkError,
)

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not all([SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY]):
    raise RuntimeError("Supabase environment variables are required.")


# ─────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print("🚀 PolyMarketAlphaAI API starting…")
    yield
    print("🛑 PolyMarketAlphaAI API shutting down…")

app = FastAPI(
    title="PolyMarketAlphaAI API",
    description="Backend API for PolyMarketAlphaAI v2",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — configure for your production domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# AUTH MIDDLEWARE
# ─────────────────────────────────────────────────────────────

async def get_current_user(request: Request) -> dict:
    """
    Extract and validate the current user from the Authorization header.

    Expects: Bearer <supabase_jwt_token>
    Returns: User dict from public.users
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")

    # Verify token with Supabase Auth
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "apikey": SUPABASE_ANON_KEY,
                    "Authorization": f"Bearer {token}",
                },
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid or expired token")

            auth_user = resp.json()
            user_id = auth_user.get("id")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token payload")

        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Auth service unavailable")

    # Fetch user from public.users
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found in database")

    return user


# ─────────────────────────────────────────────────────────────
# REQUEST/RESPONSE MODELS
# ─────────────────────────────────────────────────────────────

class ConnectTelegramRequest(BaseModel):
    code: str = Field(
        ...,
        min_length=8,
        max_length=8,
        description="8-character Telegram link code",
    )


class UpdateProfileRequest(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=50)
    last_name: str | None = Field(None, min_length=1, max_length=50)
    username: str | None = Field(None, min_length=3, max_length=20)
    email: str | None = Field(None, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class CreateSignalRequest(BaseModel):
    m_id: int = Field(..., gt=0, description="Market ID to analyze")


class ApiResponse(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None


# ─────────────────────────────────────────────────────────────
# ERROR HANDLER
# ─────────────────────────────────────────────────────────────

@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"success": False, "error": str(exc)},
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )


# ─────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "2.0.0"}


# ─────────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    """
    Get the current authenticated user's data.
    """
    return {
        "success": True,
        "data": {
            "user_id": user["user_id"],
            "email": user.get("email"),
            "first_name": user.get("first_name"),
            "last_name": user.get("last_name"),
            "username": user.get("username"),
            "account_status": user.get("account_status"),
            "trial_remaining": user.get("trial_remaining"),
            "telegram_connected": user.get("telegram_connected"),
            "telegram_username": user.get("telegram_username"),
            "profile_complete": is_profile_complete(user),
            "missing_fields": get_missing_fields(user),
        },
    }


# ─────────────────────────────────────────────────────────────
# TELEGRAM CONNECTION
# ─────────────────────────────────────────────────────────────

@app.post("/api/connect-telegram")
@app.post("/api/connect-telegram")
async def connect_telegram_endpoint(
    payload: ConnectTelegramRequest,
    user: dict = Depends(get_current_user),
):
    """
    Link the authenticated user's Telegram account.

    The authenticated website user is always the account owner.
    Telegram never creates users.
    """
    try:
        linked_user = connect_telegram(
            user_id=user["user_id"],
            code=payload.code,
        )

        return {
            "success": True,
            "data": {
                "telegram_connected": True,
                "telegram_username": linked_user.get("telegram_username"),
            },
        }

    except TelegramLinkError as e:
    raise HTTPException(
        status_code=409,
        detail=str(e),
    )

except ValueError as e:
    raise HTTPException(
        status_code=400,
        detail=str(e),
    )

except Exception as e:
    raise HTTPException(
        status_code=500,
        detail="Internal server error.",
    )


@app.delete("/api/telegram")
async def disconnect_telegram(user: dict = Depends(get_current_user)):
    """
    Unlink the Telegram account for the current user.
    """
    try:
        unlink_telegram(user["user_id"])
        return {
            "success": True,
            "data": {"telegram_connected": False},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────
# PROFILE ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.post("/api/profile")
@app.post("/api/profile")
async def update_profile_endpoint(
    payload: UpdateProfileRequest,
    user: dict = Depends(get_current_user),
):
    """
    Update the authenticated user's profile.

    Delegates all business logic to db.update_profile().
    """
    updates: dict[str, Any] = {}

    if payload.first_name is not None:
        updates["first_name"] = payload.first_name

    if payload.last_name is not None:
        updates["last_name"] = payload.last_name

    if payload.username is not None:
        updates["username"] = payload.username

    if payload.email is not None:
        updates["email"] = payload.email

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="No fields supplied.",
        )

    try:
        refreshed = update_profile(
            user_id=user["user_id"],
            updates=updates,
        )

        return {
            "success": True,
            "data": {
                "user_id": refreshed["user_id"],
                "first_name": refreshed.get("first_name"),
                "last_name": refreshed.get("last_name"),
                "username": refreshed.get("username"),
                "email": refreshed.get("email"),
                "profile_complete": is_profile_complete(refreshed),
                "missing_fields": get_missing_fields(refreshed),
            },
        }

 except ProfileIncompleteError as e:
    raise HTTPException(
        status_code=400,
        detail=str(e),
    )

except BusinessError as e:
    raise HTTPException(
        status_code=400,
        detail=str(e),
    )

except ValueError as e:
    raise HTTPException(
        status_code=400,
        detail=str(e),
    )

except Exception:
    raise HTTPException(
        status_code=500,
        detail="Internal server error.",
    )

# ─────────────────────────────────────────────────────────────
# WALLET ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/api/wallet")
async def get_user_wallet(user: dict = Depends(get_current_user)):
    """Get the current user's wallet information."""
    wallet = get_wallet(user["user_id"])

    if not wallet:
        return {
            "success": True,
            "data": {
                "token_balance": 0,
                "total_tokens_purchased": 0,
                "total_tokens_consumed": 0,
            },
        }

    return {
        "success": True,
        "data": {
            "token_balance": wallet.get("token_balance", 0),
            "total_tokens_purchased": wallet.get("total_tokens_purchased", 0),
            "total_tokens_consumed": wallet.get("total_tokens_consumed", 0),
        },
    }


# ─────────────────────────────────────────────────────────────
# SIGNAL ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/api/signals")
@app.get("/api/signals")
async def list_signals(
    user: dict = Depends(get_current_user),
):
    """
    Return the authenticated user's signal history.
    """
    return {
        "success": True,
        "data": list_signal_requests(user["user_id"]),
    }


@app.post("/api/signals")
@app.post("/api/signals")
async def create_signal_endpoint(
    payload: CreateSignalRequest,
    user: dict = Depends(get_current_user),
):
    """
    Create a new signal request.

    All business validation is delegated to db.py.
    """
    try:
        result = prepare_signal_request(
            user=user,
            m_id=payload.m_id,
        )

        signal_request = result["request"]
        account_type = result["account_type"]

        if account_type == "paid":
            consume_token(
                user_id=user["user_id"],
                amount=1,
                description=f"Signal m_id={payload.m_id}",
            )

        elif account_type == "trial":
            consume_trial(
                user_id=user["user_id"],
            )

        return {
            "success": True,
            "data": {
                "request_id": signal_request["request_id"],
                "m_id": payload.m_id,
                "status": signal_request["status"],
                "account_type": account_type,
            },
        }

    except MarketNotFoundError as e:
    raise HTTPException(
        status_code=404,
        detail=str(e),
    )

except MarketClosedError as e:
    raise HTTPException(
        status_code=409,
        detail=str(e),
    )

except ProfileIncompleteError as e:
    raise HTTPException(
        status_code=400,
        detail=str(e),
    )

except TrialExpiredError as e:
    raise HTTPException(
        status_code=403,
        detail=str(e),
    )

except WalletNotFoundError as e:
    raise HTTPException(
        status_code=404,
        detail=str(e),
    )

except InsufficientTokensError as e:
    raise HTTPException(
        status_code=403,
        detail=str(e),
    )

except BusinessError as e:
    raise HTTPException(
        status_code=400,
        detail=str(e),
    )

except ValueError as e:
    raise HTTPException(
        status_code=400,
        detail=str(e),
    )

except Exception:
    raise HTTPException(
        status_code=500,
        detail="Internal server error.",
    )
# ─────────────────────────────────────────────────────────────
# REPORTS ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/api/reports")
@app.get("/api/reports")
async def list_reports(
    m_id: int | None = None,
    user: dict = Depends(get_current_user),
):
    """
    Return market research reports.

    Optionally filter by market ID.
    """
    return {
        "success": True,
        "data": list_market_reports(m_id=m_id),
    }

def list_signal_requests(user_id: str) -> list[dict]:
    """
    Return all signal requests for a user ordered by newest first.
    """

    supabase = get_client()

    res = (
        supabase.table("signal_requests")
        .select("*, signal_deliveries(*)")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    return res.data or []

# ─────────────────────────────────────────────────────────────
# SUBSCRIPTION ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.get("/api/subscription")
async def get_subscription(user: dict = Depends(get_current_user)):
    """Get the current user's active subscription."""
    sub = get_user_subscription(user["user_id"])

    return {
        "success": True,
        "data": sub,
    }


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=os.getenv("ENV", "production") == "development",
    )
# ==========================================================
# END OF FILE app.py
# ==========================================================
