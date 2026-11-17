"""Material Estimator — FastAPI edition.

Same features as the Next.js app (sign-up, Google sign-in, guest mode, saved estimates, admin,
PDF/Excel), with every calculation done by the verified Python engine (app/engine.py).
Run locally:  uvicorn app.main:app --reload
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import catalogue, exports, supa
from .engine import estimate
from .jsnum import JSInputError, get, is_number, js_locale
from .session import PKCE, SessionMiddleware, session, safe_next, site_url

ROOT = Path(__file__).resolve().parent
STATIC = ROOT.parent / "public" / "static"

app = FastAPI(title="Material Estimator (FastAPI)", version=catalogue.ENGINE_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(SessionMiddleware)
if STATIC.exists():  # Vercel serves public/ from its CDN; this mount is for local runs
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.filters["num"] = lambda v: js_locale(v if is_number(v) else 0, "en-IN")
Locale = Literal["en-IN", "en-US"]


class NeedLogin(Exception):
    def __init__(self, next_path: str):
        self.next_path = next_path


class Forbidden(Exception):
    pass


@app.exception_handler(NeedLogin)
async def _need_login(request: Request, exc: NeedLogin):
    return RedirectResponse(f"/login?next={quote(exc.next_path)}", status_code=303)


@app.exception_handler(Forbidden)
async def _forbidden(request: Request, exc: Forbidden):
    return RedirectResponse("/dashboard", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await render(request, "message.html", status_code=exc.status_code, title="Not found" if exc.status_code == 404 else "Something went wrong",
                        message="That page does not exist." if exc.status_code == 404 else str(exc.detail))


@app.exception_handler(supa.SupaError)
async def _supa_error(request: Request, exc: supa.SupaError):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.message}, status_code=502 if exc.status >= 500 else exc.status)
    return await render(request, "message.html", status_code=502, title="Service problem", message=exc.message)


async def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    s = session(request)
    user = await s.resolve() if supa.configured() else None
    profile = await s.get_profile() if user else None
    return templates.TemplateResponse(request, name, {"user": user, "profile": profile, "configured": supa.configured(), **ctx},
                                      status_code=status_code)


async def require_user(request: Request):
    s = session(request)
    if not await s.resolve():
        raise NeedLogin(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
    return s


async def require_admin(request: Request):
    s = await require_user(request)
    if ((await s.get_profile()) or {}).get("role") != "admin":
        raise Forbidden()
    return s


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# ═════════════════════════ Pages: welcome and accounts ═════════════════════════

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return await render(request, "home.html")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str | None = None, error: str | None = None):
    if supa.configured() and await session(request).resolve():
        return redirect(safe_next(next))
    return await render(request, "login.html", next=safe_next(next), error=error)


@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/dashboard")):
    nxt = safe_next(next)
    try:
        s = await supa.sign_in_password(email.strip(), password)
    except supa.SupaError as e:
        msg = "Please confirm your email first. Check your inbox for the link." if "not confirmed" in e.message.lower() else "Email or password is incorrect."
        return await render(request, "login.html", status_code=400, next=nxt, form_error=msg, email=email)
    session(request).set_tokens(s)
    return redirect(nxt)


@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, next: str | None = None):
    return await render(request, "signup.html", next=safe_next(next))


@app.post("/signup", response_class=HTMLResponse)
async def signup(request: Request, full_name: str = Form(...), company: str = Form(""), email: str = Form(...),
                 password: str = Form(...), confirm: str = Form(...), next: str = Form("/dashboard")):
    nxt = safe_next(next)
    form = {"full_name": full_name, "company": company, "email": email}
    if password != confirm:
        return await render(request, "signup.html", status_code=400, next=nxt, form_error="Passwords do not match.", form=form)
    if len(password) < 8:
        return await render(request, "signup.html", status_code=400, next=nxt, form_error="Use at least 8 characters for the password.", form=form)
    verifier, challenge = supa.pkce_pair()
    try:
        res = await supa.sign_up(email.strip(), password, {"full_name": full_name.strip(), "company": company.strip()},
                                 f"{site_url(request)}/auth/callback?next={quote(nxt)}", challenge)
    except supa.SupaError as e:
        return await render(request, "signup.html", status_code=400, next=nxt, form_error=e.message, form=form)
    s = session(request)
    if res.get("access_token"):  # email confirmation switched off
        s.set_tokens(res)
        return redirect(nxt)
    s.set_cookie(PKCE, verifier, 60 * 60 * 24)
    return await render(request, "signup.html", next=nxt, sent_to=email.strip())


@app.get("/auth/google")
async def auth_google(request: Request, next: str | None = None):
    if not supa.configured():
        raise HTTPException(503, "Sign-in is not configured.")
    verifier, challenge = supa.pkce_pair()
    session(request).set_cookie(PKCE, verifier, 600)
    return redirect(supa.oauth_url("google", f"{site_url(request)}/auth/callback?next={quote(safe_next(next))}", challenge))


@app.get("/auth/callback")
async def auth_callback(request: Request, next: str | None = None, code: str | None = None,
                        token_hash: str | None = None, type: str | None = None, error_description: str | None = None):
    nxt = safe_next(next)
    s = session(request)
    try:
        if code:
            verifier = request.cookies.get(PKCE)
            if not verifier:
                raise supa.SupaError(400, "missing verifier")
            res = await supa.exchange_code(code, verifier)
        elif token_hash and type:
            res = await supa.verify_token_hash(token_hash, type)
        else:
            raise supa.SupaError(400, error_description or "missing code")
    except supa.SupaError:
        return redirect("/login?error=" + quote("That link is invalid or has expired. Please try again (open it in the same browser)."))
    s.clear_cookie(PKCE)
    s.set_tokens(res)
    return redirect(nxt)


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_page(request: Request):
    return await render(request, "forgot.html")


@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot(request: Request, email: str = Form(...)):
    verifier, challenge = supa.pkce_pair()
    try:
        await supa.recover(email.strip(), f"{site_url(request)}/auth/callback?next=/reset-password", challenge)
    except supa.SupaError as e:
        return await render(request, "forgot.html", status_code=400, form_error=e.message)
    session(request).set_cookie(PKCE, verifier, 60 * 60)
    return await render(request, "forgot.html", sent=True)


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_page(request: Request):
    await require_user(request)
    return await render(request, "reset.html")


@app.post("/reset-password", response_class=HTMLResponse)
async def reset(request: Request, password: str = Form(...), confirm: str = Form(...)):
    s = await require_user(request)
    if password != confirm or len(password) < 8:
        return await render(request, "reset.html", status_code=400,
                            form_error="Passwords do not match." if password != confirm else "Use at least 8 characters.")
    await supa.update_user(s.token, {"password": password})
    return redirect("/dashboard")


@app.post("/logout")
async def logout(request: Request):
    s = session(request)
    if await s.resolve():
        await supa.sign_out(s.token)
    s.clear_tokens()
    return redirect("/")


@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, saved: int = 0):
    await require_user(request)
    return await render(request, "account.html", saved=bool(saved))


@app.post("/account")
async def account(request: Request, full_name: str = Form(""), company: str = Form("")):
    s = await require_user(request)
    await supa.update("profiles", s.token, {"full_name": full_name.strip(), "company": company.strip()}, id=f"eq.{s.user['id']}")
    return redirect("/account?saved=1")


# ═════════════════════════ Pages: dashboard and estimator ═════════════════════════

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    s = await require_user(request)
    items = await supa.select("estimates", s.token, select="id,name,area,product_count,updated_at,snapshot",
                              user_id=f"eq.{s.user['id']}", order="updated_at.desc")
    return await render(request, "dashboard.html", items=items)


@app.post("/estimates/{estimate_id}/delete")
async def delete_estimate(request: Request, estimate_id: str):
    s = await require_user(request)
    await supa.delete("estimates", s.token, id=f"eq.{estimate_id}", user_id=f"eq.{s.user['id']}")
    return redirect("/dashboard")


async def estimator_page(request: Request, **config: Any) -> HTMLResponse:
    cfg = {"steps": catalogue.STEPS, "guest": False, "resumeGuest": False, "estimateId": None, "initial": None,
           "savedCatalogue": False, **config}
    return await render(request, "estimator.html", config=cfg)


@app.get("/guest", response_class=HTMLResponse)
async def guest(request: Request):
    if supa.configured() and await session(request).resolve():
        return redirect("/estimate/new")
    return await estimator_page(request, products=await catalogue.current_products(), guest=True)


@app.get("/estimate/new", response_class=HTMLResponse)
async def new_estimate(request: Request, resume: str | None = None):
    await require_user(request)
    return await estimator_page(request, products=await catalogue.current_products(), resumeGuest=resume == "guest")


async def load_estimate(s, estimate_id: str) -> dict:
    rows = await supa.select("estimates", s.token, select="id,snapshot,catalogue", id=f"eq.{estimate_id}", user_id=f"eq.{s.user['id']}")
    if not rows:
        raise HTTPException(404, "Estimate not found.")
    return rows[0]


@app.get("/estimate/{estimate_id}", response_class=HTMLResponse)
async def edit_estimate(request: Request, estimate_id: str):
    s = await require_user(request)
    est = await load_estimate(s, estimate_id)
    return await estimator_page(request, products=est["catalogue"], estimateId=est["id"], initial=est["snapshot"], savedCatalogue=True)


# ═════════════════════════ API: calculation, saving, exports ═════════════════════════

class CalcRequest(BaseModel):
    state: dict[str, Any]
    locale: Locale = "en-IN"
    catalogue: list[dict[str, Any]] | None = None


@app.get("/api/health")
async def health():
    return {"status": "ok", "engine_version": catalogue.ENGINE_VERSION, "database": supa.configured()}


@app.get("/api/products")
async def api_products():
    return await catalogue.current_products()


@app.get("/api/steps")
async def api_steps():
    return catalogue.STEPS


@app.post("/api/calc")
async def api_calc(req: CalcRequest):
    """Material list for the calculator screens (display). Saving and exports recalculate on the server."""
    products = req.catalogue if req.catalogue is not None else await catalogue.current_products()
    try:
        return estimate(req.state, products, catalogue.STEPS, req.locale, include_ids=True)
    except JSInputError as e:
        raise HTTPException(422, str(e)) from e


class Snapshot(BaseModel):
    state: dict[str, Any]
    project: dict[str, Any] = {}


class SaveRequest(BaseModel):
    id: str | None = None
    snapshot: Snapshot
    locale: Locale = "en-IN"


async def trusted_catalogue(request: Request, estimate_id: str | None) -> list[dict]:
    """The catalogue a save or export must use: the estimate's own saved one, or today's. Never the browser's."""
    if estimate_id:
        s = await require_user_api(request)
        return (await load_estimate(s, estimate_id))["catalogue"]
    return await catalogue.current_products()


async def require_user_api(request: Request):
    s = session(request)
    if not await s.resolve():
        raise HTTPException(401, "Please sign in.")
    return s


@app.post("/api/estimates")
async def api_save(request: Request, req: SaveRequest):
    s = await require_user_api(request)
    products = await trusted_catalogue(request, req.id)
    snap = req.snapshot.model_dump()
    try:
        rep = exports.report(snap, products, catalogue.STEPS, req.locale)
        state = snap["state"]
        result = estimate(state, products, catalogue.STEPS, req.locale)
    except JSInputError as e:
        raise HTTPException(422, str(e)) from e
    area = get(state, "area")
    row = {
        "name": str(snap["project"].get("name") or "Untitled project")[:200],
        "snapshot": snap,
        "results": {"project": snap["project"], "area": area if is_number(area) else None, "joints": result["joints"],
                    "openings": get(state, "openings") if is_number(get(state, "openings")) else None,
                    "lines": result["lines"], "details": rep["details"]},
        "catalogue": products,
        "engine_version": catalogue.ENGINE_VERSION,
        "area": area if is_number(area) else None,
        "product_count": len(result["lines"]),
    }
    if req.id:
        saved = await supa.update("estimates", s.token, row, id=f"eq.{req.id}", user_id=f"eq.{s.user['id']}")
        if not saved:
            raise HTTPException(404, "Estimate not found.")
        return {"id": req.id}
    created = await supa.insert("estimates", s.token, {**row, "user_id": s.user["id"]})
    return {"id": created.get("id")}


class ExportRequest(BaseModel):
    snapshot: Snapshot
    locale: Locale = "en-IN"
    estimate_id: str | None = None


@app.post("/api/export/{kind}")
async def api_export(request: Request, kind: Literal["pdf", "xlsx"], req: ExportRequest):
    products = await trusted_catalogue(request, req.estimate_id)
    try:
        rep = exports.report(req.snapshot.model_dump(), products, catalogue.STEPS, req.locale)
    except JSInputError as e:
        raise HTTPException(422, str(e)) from e
    name = exports.file_base(rep["name"])
    if kind == "pdf":
        return Response(exports.pdf(rep), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return Response(exports.xlsx(rep), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


# ═════════════════════════ Admin ═════════════════════════

@app.get("/admin/products", response_class=HTMLResponse)
async def admin_products(request: Request):
    await require_admin(request)
    catalogue.forget_cache()
    products = await catalogue.current_products()
    return await render(request, "admin_products.html", products=[{**p, "changed": catalogue.is_changed(p)} for p in products])


RATE_TEXT = ("l", "g")
RATE_NUM = ("a", "b", "n", "coats", "lf")
RATE_COLS = [("g", "Group", "text"), ("l", "Label", "text"), ("a", "Sq. ft min", "number"), ("b", "Sq. ft max", "number"),
             ("lf", "Lin. ft", "number"), ("n", "Thickness / n", "number"), ("coats", "Coats", "number")]


async def _product(pid: str) -> dict:
    catalogue.forget_cache()
    p = next((x for x in await catalogue.current_products() if x["id"] == pid), None)
    if not p:
        raise HTTPException(404, "Product not found.")
    return p


@app.get("/admin/products/{pid}", response_class=HTMLResponse)
async def admin_product(request: Request, pid: str, saved: int = 0):
    await require_admin(request)
    p = await _product(pid)
    return await render(request, "admin_product.html", product=p, changed=catalogue.is_changed(p), cols=RATE_COLS, saved=bool(saved))


@app.post("/admin/products/{pid}", response_class=HTMLResponse)
async def admin_product_save(request: Request, pid: str):
    s = await require_admin(request)
    p = await _product(pid)
    form = await request.form()
    rates, error = [], ""
    for i in range(len(p["rates"])):
        r: dict[str, Any] = {}
        for k in RATE_TEXT:
            v = str(form.get(f"r{i}_{k}", "")).strip()
            if v:
                r[k] = v
        for k in RATE_NUM:
            v = str(form.get(f"r{i}_{k}", "")).strip()
            if not v:
                continue
            try:
                n = float(v)
            except ValueError:
                n = float("nan")
            if not (n > 0 and n != float("inf")):
                error = f'Rate {i + 1}: "{k}" must be a positive number.'
                break
            r[k] = int(n) if n.is_integer() else n
        if error:
            break
        if not any(k in r for k in ("a", "b", "lf")):
            error = f"Rate {i + 1}: enter a coverage (min/max sq. ft) or a linear-feet value."
            break
        rates.append(r)
    if error:
        return await render(request, "admin_product.html", status_code=400, product=p, changed=catalogue.is_changed(p), cols=RATE_COLS, form_error=error)
    await supa.update("products", s.token, {"name": str(form.get("name", "")).strip(), "unit_desc": str(form.get("unit_desc", "")).strip(),
                                            "rates": rates, "updated_by": s.user["id"]}, id=f"eq.{pid}")
    catalogue.forget_cache()
    return redirect(f"/admin/products/{pid}?saved=1")


@app.post("/admin/products/{pid}/reset")
async def admin_product_reset(request: Request, pid: str):
    s = await require_admin(request)
    v = catalogue.verified_product(pid)
    if not v:
        raise HTTPException(404, "Product not found.")
    await supa.update("products", s.token, {"name": v["name"], "unit_desc": v["ud"], "rates": v["rates"], "updated_by": s.user["id"]}, id=f"eq.{pid}")
    catalogue.forget_cache()
    return redirect(f"/admin/products/{pid}?saved=1")


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    s = await require_admin(request)
    users = await supa.select("profiles", s.token, select="*", order="created_at.desc")
    counts: dict[str, int] = {}
    for r in await supa.select("estimates", s.token, select="user_id"):
        counts[r["user_id"]] = counts.get(r["user_id"], 0) + 1
    return await render(request, "admin_users.html", users=users, counts=counts, me=s.user["id"])


@app.post("/admin/users/{uid}/role")
async def admin_set_role(request: Request, uid: str, role: str = Form(...)):
    s = await require_admin(request)
    await supa.rpc("set_user_role", s.token, {"target": uid, "new_role": role})
    return redirect("/admin/users")
