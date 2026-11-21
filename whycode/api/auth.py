"""Sign in with GitHub: who is asking, nothing more.

Switched on by WHYCODE_AUTH=github (the live API); without it every route stays open, as in local
development and tests. The session is a signed cookie holding the GitHub login, name, avatar and
an expiry; no GitHub token is kept, since the API only needs to know who the user is.

    GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET  the GitHub OAuth app
    SESSION_SECRET                          signs session and state cookies (32+ random bytes)
    CRON_SECRET                             set by Vercel Cron; lets the keep-alive in unsigned
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

AUTH_ENV = "WHYCODE_AUTH"
SESSION_COOKIE = "whycode_session"
STATE_COOKIE = "whycode_oauth_state"
SESSION_SECONDS = 7 * 24 * 3600
STATE_SECONDS = 600
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"


class User(BaseModel):
    login: str
    name: str | None
    avatar_url: str | None


class Session(BaseModel):
    enabled: bool  # False: this API has sign-in off and every route is open
    user: User | None


def enabled() -> bool:
    return os.environ.get(AUTH_ENV, "").strip().lower() == "github"


def _secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise HTTPException(503, f"Sign-in is not configured ({name} is not set).")
    return value


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload: dict, key: str) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(token: str | None, key: str, now: float | None = None) -> dict | None:
    """The payload of a token this key signed and that has not expired, else None."""
    if not token or token.count(".") != 1:
        return None
    body, mac = token.split(".")
    want = hmac.new(key.encode(), body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_unb64(mac), want):
            return None
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < (now or time.time()):
        return None
    return payload


def current_user(request: Request) -> User | None:
    payload = unsign(request.cookies.get(SESSION_COOKIE), _secret("SESSION_SECRET"))
    return User(**payload["user"]) if payload and isinstance(payload.get("user"), dict) else None


def require_user(request: Request) -> User | None:
    """Dependency on every data route: a signed-in user, or 401 when sign-in is on."""
    if not enabled():
        return None
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Sign in with GitHub to use WhyCode.")
    return user


def require_cron(request: Request) -> None:
    """Vercel Cron sends `Authorization: Bearer $CRON_SECRET`; nothing else may call the job."""
    expected = f"Bearer {_secret('CRON_SECRET')}"
    if not hmac.compare_digest(request.headers.get("authorization", ""), expected):
        raise HTTPException(401, "Not allowed.")


def _cookie(response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name, value, max_age=max_age, httponly=True, secure=True, samesite="lax", path="/"
    )


def _safe_next(path: str | None) -> str:
    """Only a path on this site, so the login cannot be used to redirect elsewhere."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


router = APIRouter(prefix="/api/auth")


@router.get("/me", response_model=Session)
def me(request: Request):
    """Always 200, so a signed-out visitor's first page load logs no failed request."""
    if not enabled():
        return Session(enabled=False, user=None)
    return Session(enabled=True, user=current_user(request))


@router.get("/login")
def login(next: Annotated[str | None, Query()] = None):
    state = secrets.token_urlsafe(24)
    key = _secret("SESSION_SECRET")
    params = {
        "client_id": _secret("GITHUB_CLIENT_ID"),
        "scope": "read:user",
        "state": state,
        "allow_signup": "true",
    }
    response = RedirectResponse(f"{AUTHORIZE_URL}?{urlencode(params)}", status_code=302)
    cookie = sign(
        {"state": state, "next": _safe_next(next), "exp": time.time() + STATE_SECONDS}, key
    )
    _cookie(response, STATE_COOKIE, cookie, STATE_SECONDS)
    return response


def exchange(code: str, client: httpx.Client) -> User:
    """Trade the OAuth code for a token, read the user, and drop the token."""
    token = (
        client.post(
            TOKEN_URL,
            data={
                "client_id": _secret("GITHUB_CLIENT_ID"),
                "client_secret": _secret("GITHUB_CLIENT_SECRET"),
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        .json()
        .get("access_token")
    )
    if not token:
        raise HTTPException(401, "GitHub did not accept the sign-in. Try again.")
    res = client.get(
        USER_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    if res.status_code != 200:
        raise HTTPException(502, "Could not read your GitHub profile. Try again.")
    data = res.json()
    return User(login=data["login"], name=data.get("name"), avatar_url=data.get("avatar_url"))


def http_client() -> httpx.Client:
    return httpx.Client(timeout=10)


@router.get("/callback")
def callback(
    request: Request,
    client: Annotated[httpx.Client, Depends(http_client)],
    code: str = "",
    state: str = "",
):
    key = _secret("SESSION_SECRET")
    saved = unsign(request.cookies.get(STATE_COOKIE), key)
    if not code or not saved or not hmac.compare_digest(saved.get("state", ""), state):
        raise HTTPException(
            400, "This sign-in link expired or was not started here. Sign in again."
        )
    with client:
        user = exchange(code, client)
    response = RedirectResponse(_safe_next(saved.get("next")), status_code=302)
    session = sign({"user": user.model_dump(), "exp": time.time() + SESSION_SECONDS}, key)
    _cookie(response, SESSION_COOKIE, session, SESSION_SECONDS)
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


@router.post("/logout", status_code=204)
def logout():
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
