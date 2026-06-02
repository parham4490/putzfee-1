"""Firebase Cloud Messaging (HTTP v1) push notifications.

Legacy server keys are intentionally not supported — the legacy API was
shut down by Google in 2024. The service account JSON is provided via
``GOOGLE_APPLICATION_CREDENTIALS_JSON_B64`` and we exchange it for an
OAuth2 access token at request time, caching the token until it expires.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional

import httpx

from .config import get_settings
from .database import database, device_tokens, notifications

logger = logging.getLogger("putzfee.push")

_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

# Cached service-account credentials (parsed) and access token.
_token_lock = asyncio.Lock()
_cached_access_token: Optional[str] = None
_cached_token_expires_at: float = 0.0


def _service_account_dict() -> Optional[Dict[str, Any]]:
    s = get_settings()
    raw_b64 = s.GOOGLE_APPLICATION_CREDENTIALS_JSON_B64
    if not raw_b64:
        return None
    try:
        return json.loads(base64.b64decode(raw_b64).decode("utf-8"))
    except Exception:
        logger.exception("Invalid GOOGLE_APPLICATION_CREDENTIALS_JSON_B64")
        return None


async def _get_access_token() -> Optional[str]:
    global _cached_access_token, _cached_token_expires_at
    creds = _service_account_dict()
    if creds is None:
        return None

    async with _token_lock:
        now = time.time()
        if _cached_access_token and now < _cached_token_expires_at - 60:
            return _cached_access_token

        # Sign a JWT manually (avoiding google-auth's threaded credentials).
        from jose import jwt as jose_jwt

        iat = int(now)
        payload = {
            "iss": creds["client_email"],
            "scope": _FCM_SCOPE,
            "aud": _OAUTH_TOKEN_URL,
            "iat": iat,
            "exp": iat + 3500,
        }
        try:
            assertion = jose_jwt.encode(
                payload, creds["private_key"], algorithm="RS256"
            )
        except Exception:
            logger.exception("Failed to sign service-account JWT")
            return None

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                _OAUTH_TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
        if r.status_code != 200:
            logger.error("OAuth token exchange failed: %s %s", r.status_code, r.text)
            return None
        data = r.json()
        _cached_access_token = data["access_token"]
        _cached_token_expires_at = now + int(data.get("expires_in", 3600))
        return _cached_access_token


async def _send_to_token(
    token: str, title: str, body: str, data: Dict[str, Any]
) -> bool:
    """Send one FCM v1 message. Return False if the token is unregistered."""
    s = get_settings()
    if not s.FCM_PROJECT_ID:
        return True  # pretend success when push is disabled
    access = await _get_access_token()
    if not access:
        return True

    url = f"https://fcm.googleapis.com/v1/projects/{s.FCM_PROJECT_ID}/messages:send"
    payload: Dict[str, Any] = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in data.items()},
            "android": {"priority": "HIGH"},
        }
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {access}"},
            json=payload,
        )
    if r.status_code == 200:
        return True
    if r.status_code in (400, 404):
        # Token registration is bad → remove it.
        try:
            error_status = r.json().get("error", {}).get("status", "")
        except Exception:
            error_status = ""
        if error_status in (
            "INVALID_ARGUMENT",
            "UNREGISTERED",
            "NOT_FOUND",
        ) or r.status_code == 404:
            return False
    logger.warning("FCM send failed %s: %s", r.status_code, r.text)
    return True


async def _delete_dead_token(token: str) -> None:
    await database.execute(
        device_tokens.delete().where(device_tokens.c.token == token)
    )


async def push_to_user(
    user_id: int,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    persist: bool = True,
) -> None:
    """Send *title*/*body* to every device of *user_id*.

    The notification is also persisted to the ``notifications`` table by
    default so that it shows up in the in-app history.
    """
    data = data or {}
    is_duplicate = False
    if persist:
        # Check for duplicate notification in the last 5 minutes
        from datetime import datetime, timedelta
        five_minutes_ago = datetime.now() - timedelta(minutes=5)
        existing = await database.fetch_one(
            notifications.select().where(
                (notifications.c.user_id == user_id) &
                (notifications.c.title == title) &
                (notifications.c.body == body) &
                (notifications.c.created_at >= five_minutes_ago)
            )
        )
        if existing is None:
            await database.execute(
                notifications.insert().values(
                    user_id=user_id, title=title, body=body, payload=data
                )
            )
        else:
            is_duplicate = True
    
    # Only send FCM if not a duplicate
    if not is_duplicate:
        rows = await database.fetch_all(
            device_tokens.select().where(device_tokens.c.user_id == user_id)
        )
        for r in rows:
            ok = await _send_to_token(r["token"], title, body, data)
            if not ok:
                await _delete_dead_token(r["token"])


async def push_to_admins(
    title: str, body: str, data: Optional[Dict[str, Any]] = None
) -> None:
    """Broadcast to all admins (in-app + FCM)."""
    from .database import users  # local import to avoid cycle at module load

    rows = await database.fetch_all(
        users.select().where(users.c.is_admin == True).where(users.c.is_active == True)  # noqa: E712
    )
    for u in rows:
        await push_to_user(u["id"], title, body, data, persist=True)
