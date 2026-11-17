"""Pages, API and safety rules of the FastAPI app (no database needed)."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.jsnum import js_locale, js_round, js_str
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
C = TestClient(app, base_url="http://testserver")
SAME_SITE = {"Origin": "http://testserver"}


def test_js_number_rules():
    assert js_round(2.5) == 3 and js_round(-2.5) == -2
    assert js_str(2.0) == "2" and js_str(1e21) == "1e+21"
    assert js_locale(1234567.8915, "en-IN") == "12,34,567.892"
    assert js_locale(1234567.8915, "en-US") == "1,234,567.892"


def test_public_pages_load():
    for path in ("/", "/login", "/signup", "/guest", "/forgot-password", "/api/health", "/api/docs"):
        assert C.get(path).status_code == 200, path


def test_private_pages_need_sign_in():
    for path in ("/dashboard", "/estimate/new", "/account", "/admin/products", "/admin/users"):
        r = C.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/login"), path


def test_calc_matches_known_values():
    r = C.post("/api/calc", headers=SAME_SITE, json={"state": {"area": 1200, "openings": 80, "rows": {
        "s4": [{"pid": "genesis", "ri": 1}], "s5": [{"pid": "epsboard", "thick": 2}]}}})
    assert r.status_code == 200
    body = r.json()
    assert body["joints"] == 540                                   # Math.round(1200 * 0.45)
    units = {l["layer"]: l["units"] for l in body["lines"]}
    assert units["Adhesive"] == 5                                   # ceil(1200 / 260)
    assert units["EPS Insulation Board"] == 17                      # ceil(1200 / 144 * 2)


def test_bad_input_is_rejected():
    r = C.post("/api/calc", headers=SAME_SITE, json={"state": {"area": "big"}})
    assert r.status_code == 422


def test_cross_site_posts_are_blocked():
    assert C.post("/api/calc", json={"state": {}}).status_code == 403
    assert C.post("/api/calc", headers={"Origin": "https://evil.example"}, json={"state": {}}).status_code == 403


def test_saving_needs_sign_in():
    r = C.post("/api/estimates", headers=SAME_SITE, json={"snapshot": {"state": {"area": 1}}})
    assert r.status_code == 401


def test_exports_are_files():
    snap = {"snapshot": {"state": {"area": 1200, "rows": {"s4": [{"pid": "genesis", "ri": 1}]}}, "project": {"name": "Tower"}}}
    pdf = C.post("/api/export/pdf", headers=SAME_SITE, json=snap)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    xlsx = C.post("/api/export/xlsx", headers=SAME_SITE, json=snap)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_open_redirects_are_refused():
    r = C.get("/login?next=//evil.example")
    assert 'value="/dashboard"' in r.text


def test_built_screens_contain_verbatim_calculator():
    ui = (ROOT / "public" / "static" / "estimator-ui.js").read_text(encoding="utf-8")
    assert "BEGIN verbatim calculator_v8.html" in ui and "compute=function(){return apiResult;}" in ui
