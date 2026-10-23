"""Login, logout and auth status endpoints. Rationale: see app/auth/__init__.py."""

import math

from fastapi import APIRouter, Depends, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.auth import rate_limit
from app.auth.deps import AuthContext, get_auth
from app.auth.pin import verify_pin
from app.auth.session import SESSION_COOKIE, SESSION_MAX_AGE, encode_session
from app.config import get_settings
from app.schemas import AuthStatus, LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def _locked_for() -> int:
    return math.ceil(rate_limit.login_limiter.locked_for())


@router.post("/login", response_model=AuthStatus)
async def login(body: LoginRequest, response: Response):
    settings = get_settings()
    limiter = rate_limit.login_limiter
    async with limiter.lock:
        locked = math.ceil(limiter.locked_for())
        if locked > 0:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many attempts", "retry_after": locked},
                headers={"Retry-After": str(locked)},
            )

        ok = await run_in_threadpool(verify_pin, body.pin, settings.owner_pin_hash)
        if not ok:
            limiter.record_failure()
            return JSONResponse(status_code=401, content={"detail": "Wrong PIN"})

        limiter.record_success()

    response.set_cookie(
        SESSION_COOKIE,
        encode_session(settings.owner_user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthStatus(mode="owner", login_locked_for=0)


@router.post("/logout", response_model=AuthStatus)
def logout(response: Response):
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthStatus(mode="demo", login_locked_for=_locked_for())


@router.get("/me", response_model=AuthStatus)
def me(auth: AuthContext = Depends(get_auth)):
    return AuthStatus(mode=auth.mode, login_locked_for=_locked_for())
