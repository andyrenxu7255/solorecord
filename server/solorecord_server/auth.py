import hashlib
import ssl
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, Header, HTTPException, status
import httpx
import jwt
from jwt import PyJWKClient
from ldap3 import ALL, BASE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn

from .config import get_settings
from .db import get_db
from .utils import new_id, now_iso, row_to_dict


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_or_get_user(display_name: str, email: str = "", role: str = "user") -> dict:
    subject = email or display_name
    return create_or_get_user_for_subject(subject, display_name, email, role)


def create_or_get_user_for_subject(
    subject: str,
    display_name: str,
    email: str = "",
    role: str = "user",
) -> dict:
    normalized_subject = subject.strip() or email or display_name
    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM users WHERE sso_subject = ?",
            (normalized_subject,),
        ).fetchone()
        if existing:
            if (
                existing["display_name"] != display_name
                or existing["email"] != email
                or existing["role"] != role
            ):
                db.execute(
                    """
                    UPDATE users SET display_name = ?, email = ?, role = ?
                    WHERE id = ?
                    """,
                    (display_name, email, role, existing["id"]),
                )
                existing = db.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
            return row_to_dict(existing)
        user_id = new_id("usr")
        db.execute(
            """
            INSERT INTO users (id, sso_subject, display_name, email, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, normalized_subject, display_name, email, role, now_iso()),
        )
        return row_to_dict(db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def ldap_login(username: str, password: str) -> dict:
    settings = get_settings()
    login_name = username.strip()
    if not settings.ldap_enabled:
        raise HTTPException(status_code=400, detail="LDAP login is not configured")
    if not login_name or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    if len(login_name) > 128 or len(password) > 512:
        raise HTTPException(status_code=400, detail="Username or password is too long")
    if not settings.ldap_server or not (
        settings.ldap_bind_dn_template
        or (settings.ldap_lookup_bind_dn and settings.ldap_lookup_bind_password and settings.ldap_search_dn)
    ):
        raise HTTPException(status_code=400, detail="LDAP server or bind DN is not configured")
    user_dn = _ldap_user_dn(login_name) if settings.ldap_bind_dn_template else ""
    user_dn, attributes = _ldap_fetch_user(login_name, user_dn, password)
    display_name = _first_attr(
        attributes,
        [settings.ldap_display_name_key, settings.ldap_username_key, "displayName", "cn", "uid"],
    ) or login_name
    email = _ldap_email(login_name, attributes)
    subject = f"ldap:{user_dn}"
    role = _ldap_role(login_name, user_dn, attributes)
    user = create_or_get_user_for_subject(subject, display_name, email, role)
    return {"user": user, **create_session(user["id"])}


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


def _ldap_server() -> Server:
    settings = get_settings()
    return Server(
        settings.ldap_server,
        get_info=ALL,
        connect_timeout=settings.ldap_timeout_seconds,
        tls=Tls(validate=ssl.CERT_REQUIRED if settings.ldap_tls_validate else ssl.CERT_NONE),
    )


def _ldap_user_dn(username: str) -> str:
    settings = get_settings()
    escaped_username = escape_rdn(username)
    return settings.ldap_bind_dn_template.replace("XXX", escaped_username).replace("%s", escaped_username)


def _ldap_search_filter(username: str) -> str:
    settings = get_settings()
    raw_filter = settings.ldap_search_filter.strip() or "({username_key}={username})"
    escaped_username = escape_filter_chars(username)
    if "%s" in raw_filter:
        rendered = raw_filter % escaped_username
    elif "{" in raw_filter:
        rendered = raw_filter.format(
            username=escaped_username,
            username_key=settings.ldap_username_key,
        )
    elif "(" not in raw_filter:
        rendered = f"({raw_filter}={escaped_username})"
    else:
        rendered = raw_filter
    if not rendered.startswith("("):
        rendered = f"({rendered})"
    return rendered


def _ldap_fetch_user(username: str, user_dn: str, password: str) -> tuple[str, dict]:
    settings = get_settings()
    try:
        if settings.ldap_lookup_bind_dn and settings.ldap_lookup_bind_password and settings.ldap_search_dn:
            found_dn, attributes = _ldap_lookup_user(username)
            authenticated_dn = found_dn or user_dn
            _ldap_bind_credentials(authenticated_dn, password)
            return authenticated_dn, attributes
        return user_dn, _ldap_fetch_user_with_bind(username, user_dn, password)
    except HTTPException:
        raise
    except LDAPException as exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        ) from exception


def _ldap_lookup_user(username: str) -> tuple[str, dict]:
    settings = get_settings()
    with Connection(
        _ldap_server(),
        user=settings.ldap_lookup_bind_dn,
        password=settings.ldap_lookup_bind_password,
        auto_bind=True,
        receive_timeout=settings.ldap_timeout_seconds,
    ) as conn:
        entry = _ldap_search_entry(conn, username)
        if not entry:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return entry.entry_dn, entry.entry_attributes_as_dict


def _ldap_bind_credentials(user_dn: str, password: str) -> None:
    settings = get_settings()
    if not user_dn:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    with Connection(
        _ldap_server(),
        user=user_dn,
        password=password,
        auto_bind=True,
        receive_timeout=settings.ldap_timeout_seconds,
    ):
        return


def _ldap_fetch_user_with_bind(username: str, user_dn: str, password: str) -> dict:
    settings = get_settings()
    with Connection(
        _ldap_server(),
        user=user_dn,
        password=password,
        auto_bind=True,
        receive_timeout=settings.ldap_timeout_seconds,
    ) as conn:
        entry = _ldap_search_entry(conn, username)
        if not entry and user_dn:
            conn.search(
                user_dn,
                "(objectClass=*)",
                search_scope=BASE,
                attributes=_ldap_attributes(),
                size_limit=1,
            )
            entry = conn.entries[0] if conn.entries else None
        if not entry:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return entry.entry_attributes_as_dict


def _ldap_search_entry(conn: Connection, username: str):
    settings = get_settings()
    if not settings.ldap_search_dn:
        return None
    conn.search(
        settings.ldap_search_dn,
        _ldap_search_filter(username),
        search_scope=SUBTREE,
        attributes=_ldap_attributes(),
        size_limit=1,
    )
    return conn.entries[0] if conn.entries else None


def _ldap_attributes() -> list[str]:
    settings = get_settings()
    return list(
        dict.fromkeys(
            [
                settings.ldap_username_key,
                settings.ldap_email_key,
                settings.ldap_display_name_key,
                "cn",
                "uid",
                "mail",
                "email",
                "displayName",
                "memberOf",
            ]
        )
    )


def _ldap_role(username: str, user_dn: str, attributes: dict) -> str:
    settings = get_settings()
    configured_admins = {
        item.strip().lower()
        for item in settings.ldap_admin_users.split(",")
        if item.strip()
    }
    if username.lower() in configured_admins or user_dn.lower() in configured_admins:
        return "admin"
    admin_group = settings.ldap_admin_group_dn.strip().lower()
    if admin_group:
        groups = _attr_list(attributes.get("memberOf") or attributes.get("memberof"))
        if any(str(group).strip().lower() == admin_group for group in groups):
            return "admin"
    return settings.ldap_default_role if settings.ldap_default_role in {"admin", "user"} else "user"


def _first_attr(attributes: dict, names: list[str]) -> str:
    lowered = {key.lower(): value for key, value in attributes.items()}
    for name in names:
        value = lowered.get((name or "").lower())
        values = _attr_list(value)
        if values:
            return str(values[0])
    return ""


def _ldap_email(username: str, attributes: dict) -> str:
    settings = get_settings()
    email = _first_attr(attributes, [settings.ldap_email_key, "mail", "email"]).strip()
    postfix = settings.ldap_email_postfix.strip()
    if email and ("@" in email or not postfix):
        return email
    if email and postfix:
        return f"{email}{_normalized_email_postfix(postfix)}"
    if postfix:
        return f"{username}{_normalized_email_postfix(postfix)}"
    return ""


def _normalized_email_postfix(postfix: str) -> str:
    if not postfix:
        return ""
    return postfix if postfix.startswith("@") else f"@{postfix}"


def _attr_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    if value == "":
        return []
    return [value]

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
