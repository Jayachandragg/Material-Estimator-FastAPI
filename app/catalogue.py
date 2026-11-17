"""Product catalogue: from the database (admin-editable), or the verified values when no database is set."""
from __future__ import annotations

import time

from . import supa
from .engine import load_products, load_steps

VERIFIED = load_products()          # exact copy of calculator_v8.html's `const P`
STEPS = load_steps()
ENGINE_VERSION = "calculator_v8-py"  # stored with saved estimates: verified v8 values, Python engine
_CACHE: dict = {"at": 0.0, "data": None}
TTL = 60


def to_engine_shape(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "unit": row["unit"], "ud": row.get("unit_desc", ""), "rates": row["rates"]}


async def current_products() -> list[dict]:
    if not supa.configured():
        return VERIFIED
    if _CACHE["data"] is not None and time.time() - _CACHE["at"] < TTL:
        return _CACHE["data"]
    rows = await supa.select("products", None, select="id,name,unit,unit_desc,rates", order="sort_order")
    if not rows:
        raise supa.SupaError(500, "The product catalogue is empty. Run supabase/seed_products.sql.")
    _CACHE["data"], _CACHE["at"] = [to_engine_shape(r) for r in rows], time.time()
    return _CACHE["data"]


def forget_cache() -> None:
    _CACHE["data"] = None


def verified_product(pid: str) -> dict | None:
    return next((p for p in VERIFIED if p["id"] == pid), None)


def _norm(rates: list) -> str:
    import json
    return json.dumps([dict(sorted(r.items())) for r in rates], sort_keys=True)


def is_changed(p: dict) -> bool:
    v = verified_product(p["id"])
    return v is None or v["name"] != p["name"] or v["ud"] != p["ud"] or _norm(v["rates"]) != _norm(p["rates"])
