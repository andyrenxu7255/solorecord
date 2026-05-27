import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, Header, HTTPException, status
import jwt
from jwt import PyJWKClient
import httpx

from .config import get_settings
from .db import get_db
from .utils import new_id, now_iso, row_to_dict


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_or_get_user(display_name: str, email: str = "", role: str = "user") -> dict:
    subject = email or display_name
    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM users WHERE sso_subject = ?",
            (subject,),
        ).fetchone()
        if existing:
            return row_to_dict(existing)
        user_id = new_id("usr")
        db.execute(
            """
            INSERT INTO users (id, sso_subject, display_name, email, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, subject, display_name, email, role, now_iso()),
        )
        return row_to_dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def build_sso_authorize_url(redirect_after: str = "/") -> str:
    settings = get_settings()
    if not settings.sso_issuer or not settings.sso_client_id or not settings.sso_redirect_uri:
        raise HTTPException(status_code=400, detail="SSO is not configured")
    state = new_id("state")
    nonce = new_id("nonce")
    with get_db() as db:
        db.execute(
            "INSERT INTO sso_states (state, nonce, redirect_after, created_at) VALUES (?, ?, ?, ?)",
            (state, nonce, _safe_redirect_after(redirect_after), now_iso()),
        )
    params = urlencode(
        {
            "app_id": settings.sso_client_id,
            "client_id": settings.sso_client_id,
            "redirect_uri": settings.sso_redirect_uri,
            "response_type": "code",
            "scope": settings.sso_scope,
            "state": state,
            "nonce": nonce,
        }
    )
    return f"{_authorize_url()}?{params}"


def exchange_sso_code(code: str, state: str) -> dict:
    settings = get_settings()
    with get_db() as db:
        saved_state = db.execute("SELECT * FROM sso_states WHERE state = ?", (state,)).fetchone()
        if saved_state:
            db.execute("DELETE FROM sso_states WHERE state = ?", (state,))
    if not saved_state:
        raise HTTPException(status_code=400, detail="Invalid SSO state")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.sso_redirect_uri,
        "app_id": settings.sso_client_id,
        "client_id": settings.sso_client_id,
    }
    if settings.sso_client_secret:
        data["client_secret"] = settings.sso_client_secret
    with httpx.Client(timeout=20) as client:
        response = client.post(_token_url(), data=data)
        response.raise_for_status()
    token_payload = response.json()
    claims = _verify_id_token(token_payload.get("id_token", ""), saved_state["nonce"])
    if not claims and token_payload.get("access_token"):
        claims = _fetch_userinfo(token_payload["access_token"])
    if not claims:
        raise HTTPException(status_code=400, detail="SSO did not return user identity")
    email = claims.get("email", "")
    display_name = claims.get("name") or claims.get("preferred_username") or email or claims.get("sub", "Synology User")
    user = create_or_get_user(display_name, email, role="user")
    return {"user": user, **create_session(user["id"]), "redirect_after": saved_state["redirect_after"]}


def create_session(user_id: str) -> dict:
    settings = get_settings()
    token = new_id("tok")
    session_id = new_id("ses")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    with get_db() as db:
        db.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user_id, hash_token(token), expires_at.isoformat(), now_iso()),
        )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
    }


def current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")
    token = authorization.split(" ", 1)[1].strip()
    token_digest = hash_token(token)
    with get_db() as db:
        row = db.execute(
            """
            SELECT users.*, sessions.expires_at AS session_expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (token_digest,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
    user = row_to_dict(row)
    expires_at = datetime.fromisoformat(user.pop("session_expires_at"))
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access token expired")
    return user


CurrentUser = Annotated[dict, Depends(current_user)]


def require_admin(user: CurrentUser) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user


def external_client(authorization: Annotated[str | None, Header()] = None) -> dict:
    token = _bearer_token(authorization)
    configured = _external_tokens()
    if not token or not configured:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing external API token")
    for name, expected in configured.items():
        if secrets.compare_digest(token, expected):
            return {"client": name}
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid external API token")


ExternalClient = Annotated[dict, Depends(external_client)]


def _verify_id_token(id_token: str, nonce: str) -> dict:
    settings = get_settings()
    if not id_token:
        return {}
    if settings.sso_verify_mode == "demo":
        claims = jwt.decode(id_token, options={"verify_signature": False, "verify_aud": False})
    else:
        key = ""
        algorithms = ["RS256", "HS256"]
        if settings.sso_jwks_url:
            key = PyJWKClient(settings.sso_jwks_url).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key,
            algorithms=algorithms,
            audience=settings.sso_client_id or None,
            issuer=settings.sso_issuer or None,
        )
    if claims.get("nonce") and claims["nonce"] != nonce:
        raise HTTPException(status_code=400, detail="Invalid SSO nonce")
    return claims


def _fetch_userinfo(access_token: str) -> dict:
    settings = get_settings()
    if not settings.sso_userinfo_url:
        return {}
    with httpx.Client(timeout=20) as client:
        response = client.get(settings.sso_userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
    return response.json()


def _authorize_url() -> str:
    settings = get_settings()
    if settings.sso_authorize_url:
        return settings.sso_authorize_url
    return f"{_sso_base()}/SSOOauth.cgi"


def _token_url() -> str:
    settings = get_settings()
    if settings.sso_token_url:
        return settings.sso_token_url
    return f"{_sso_base()}/SSOAccessToken.cgi"


def _sso_base() -> str:
    settings = get_settings()
    issuer = settings.sso_issuer.rstrip("/")
    if issuer.endswith("/webman/sso"):
        return issuer
    return f"{issuer}/webman/sso"


def _safe_redirect_after(redirect_after: str) -> str:
    value = (redirect_after or "/").strip()
    if value == "solorecord://auth/callback":
        return value
    if value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return authorization.strip()


def _external_tokens() -> dict[str, str]:
    settings = get_settings()
    configured_tokens = settings.external_api_tokens
    try:
        with get_db() as db:
            row = db.execute("SELECT value FROM app_config WHERE key='external_api_tokens'").fetchone()
            if row and row["value"]:
                configured_tokens = row["value"]
    except Exception:
        configured_tokens = settings.external_api_tokens
    result: dict[str, str] = {}
    for index, item in enumerate(configured_tokens.split(","), start=1):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            name, token = item.split(":", 1)
        else:
            name, token = f"client_{index}", item
        if token.strip():
            result[name.strip() or f"client_{index}"] = token.strip()
    return result
