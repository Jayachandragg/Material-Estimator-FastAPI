"""Sign-in sessions in httpOnly cookies, refreshed automatically.

SessionMiddleware gives each request a lazily-resolved `request.state.session`. Resolving it checks
the access token with Supabase, refreshes it with the refresh token when needed, and queues any
cookie changes, which the middleware writes onto the response.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

from . import supa

ACCESS, REFRESH, PKCE = "sb_access", "sb_refresh", "sb_pkce"


class Session:
    def __init__(self, request: Request):
        self.request = request
        self._resolved = False
        self.user: dict | None = None
        self.token: str | None = None
        self.profile: dict | None = None
        self._set: dict[str, tuple[str, int]] = {}
        self._clear: set[str] = set()

    # ── cookie changes, applied by the middleware ──
    def set_tokens(self, s: dict) -> None:
        self._set[ACCESS] = (s["access_token"], int(s.get("expires_in") or 3600))
        self._set[REFRESH] = (s["refresh_token"], 60 * 60 * 24 * 30)
        self.user, self.token, self._resolved, self.profile = s.get("user"), s["access_token"], True, None
        self._clear -= {ACCESS, REFRESH}

    def clear_tokens(self) -> None:
        self._clear |= {ACCESS, REFRESH}
        self._set.pop(ACCESS, None)
        self._set.pop(REFRESH, None)
        self.user, self.token, self._resolved, self.profile = None, None, True, None

    def set_cookie(self, name: str, value: str, max_age: int) -> None:
        self._set[name] = (value, max_age)
        self._clear.discard(name)

    def clear_cookie(self, name: str) -> None:
        self._clear.add(name)
        self._set.pop(name, None)

    async def resolve(self) -> dict | None:
        """The signed-in user, or None."""
        if self._resolved:
            return self.user
        self._resolved = True
        if not supa.configured():
            return None
        at, rt = self.request.cookies.get(ACCESS), self.request.cookies.get(REFRESH)
        if at:
            try:
                self.user, self.token = await supa.get_user(at), at
                return self.user
            except supa.SupaError:
                pass
        if rt:
            try:
                self.set_tokens(await supa.refresh(rt))
                return self.user
            except supa.SupaError:
                self.clear_tokens()
        return None

    async def get_profile(self) -> dict | None:
        if self.profile is None and await self.resolve():
            rows = await supa.select("profiles", self.token, select="*", id=f"eq.{self.user['id']}")
            self.profile = rows[0] if rows else None
        return self.profile

    def apply(self, response: Response) -> None:
        secure = site_url(self.request).startswith("https://")
        for name in self._clear:
            response.delete_cookie(name, path="/")
        for name, (value, max_age) in self._set.items():
            response.set_cookie(name, value, max_age=max_age, path="/", httponly=True, secure=secure, samesite="lax")


SAFE = {"GET", "HEAD", "OPTIONS"}
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Any:
        # Cross-site request forgery: every form post and API write must come from this site.
        if request.method not in SAFE:
            source = request.headers.get("origin") or request.headers.get("referer")
            if not source or urlparse(source).netloc != urlparse(site_url(request)).netloc:
                return PlainTextResponse("Cross-site request blocked.", status_code=403)
        request.state.session = Session(request)
        response = await call_next(request)
        request.state.session.apply(response)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


def session(request: Request) -> Session:
    return request.state.session


def site_url(request: Request) -> str:
    """https://host of this site as the visitor sees it (Vercel terminates HTTPS in front of the app)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def safe_next(value: str | None, default: str = "/dashboard") -> str:
    """Only allow redirects to paths inside this site."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value
    return default
