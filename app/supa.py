"""Minimal Supabase client: Auth (GoTrue) and the database REST API (PostgREST).

Every database call is made WITH the signed-in user's access token, so the same row-level
security rules as the Next.js app decide what each person can read or change.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any

import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")


def configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


class SupaError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _headers(token: str | None = None, extra: dict | None = None) -> dict:
    h = {"apikey": SUPABASE_KEY}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if extra:
        h.update(extra)
    return h


def _message(r: httpx.Response) -> str:
    try:
        j = r.json()
    except ValueError:
        return r.text[:200] or f"HTTP {r.status_code}"
    for k in ("msg", "message", "error_description", "error"):
        if isinstance(j, dict) and j.get(k):
            return str(j[k])
    return f"HTTP {r.status_code}"


async def _call(method: str, path: str, *, token: str | None = None, params: dict | None = None,
                json: Any = None, prefer: str | None = None) -> Any:
    if not configured():
        raise SupaError(503, "Supabase is not configured (set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY).")
    extra = {"Prefer": prefer} if prefer else None
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, SUPABASE_URL + path, headers=_headers(token, extra), params=params, json=json)
    if r.status_code >= 400:
        raise SupaError(r.status_code, _message(r))
    if not r.content:
        return None
    return r.json()


# ───────── PKCE ─────────

def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def oauth_url(provider: str, redirect_to: str, challenge: str) -> str:
    q = httpx.QueryParams({"provider": provider, "redirect_to": redirect_to,
                           "code_challenge": challenge, "code_challenge_method": "s256"})
    return f"{SUPABASE_URL}/auth/v1/authorize?{q}"


# ───────── Auth ─────────

async def sign_in_password(email: str, password: str) -> dict:
    return await _call("POST", "/auth/v1/token", params={"grant_type": "password"},
                       json={"email": email, "password": password})


async def refresh(refresh_token: str) -> dict:
    return await _call("POST", "/auth/v1/token", params={"grant_type": "refresh_token"},
                       json={"refresh_token": refresh_token})


async def sign_up(email: str, password: str, data: dict, redirect_to: str, challenge: str) -> dict:
    return await _call("POST", "/auth/v1/signup", params={"redirect_to": redirect_to},
                       json={"email": email, "password": password, "data": data,
                             "code_challenge": challenge, "code_challenge_method": "s256"})


async def recover(email: str, redirect_to: str, challenge: str) -> None:
    await _call("POST", "/auth/v1/recover", params={"redirect_to": redirect_to},
                json={"email": email, "code_challenge": challenge, "code_challenge_method": "s256"})


async def exchange_code(code: str, verifier: str) -> dict:
    return await _call("POST", "/auth/v1/token", params={"grant_type": "pkce"},
                       json={"auth_code": code, "code_verifier": verifier})


async def verify_token_hash(token_hash: str, otp_type: str) -> dict:
    return await _call("POST", "/auth/v1/verify", json={"type": otp_type, "token_hash": token_hash})


async def get_user(token: str) -> dict:
    return await _call("GET", "/auth/v1/user", token=token)


async def update_user(token: str, attrs: dict) -> dict:
    return await _call("PUT", "/auth/v1/user", token=token, json=attrs)


async def sign_out(token: str) -> None:
    try:
        await _call("POST", "/auth/v1/logout", token=token)
    except SupaError:
        pass


# ───────── Database (PostgREST) ─────────

async def select(table: str, token: str | None, **params: str) -> list[dict]:
    return await _call("GET", f"/rest/v1/{table}", token=token, params=params) or []


async def insert(table: str, token: str, row: dict) -> dict:
    rows = await _call("POST", f"/rest/v1/{table}", token=token, json=row, prefer="return=representation")
    return rows[0] if rows else {}


async def update(table: str, token: str, row: dict, **filters: str) -> list[dict]:
    return await _call("PATCH", f"/rest/v1/{table}", token=token, params=filters, json=row,
                       prefer="return=representation") or []


async def delete(table: str, token: str, **filters: str) -> None:
    await _call("DELETE", f"/rest/v1/{table}", token=token, params=filters)


async def rpc(fn: str, token: str, args: dict) -> Any:
    return await _call("POST", f"/rest/v1/rpc/{fn}", token=token, json=args)
