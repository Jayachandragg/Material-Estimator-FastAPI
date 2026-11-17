"""Material Estimator calculation engine: a line-by-line Python port of calculator_v8.html.

Ported functions (JavaScript name -> Python name):
    jointsValue -> joints_value, openingsValue -> openings_value, effQty -> eff_qty,
    avgCov -> avg_cov, findJointsRate -> find_joints_rate, compute -> compute,
    lineInfo -> line_info, plus the review/export rows (reportData) -> estimate.

No value, rule or formula was added or changed. tests/test_parity.py proves it against the original
JavaScript running on thousands of generated estimates (see tools/make_cases.mjs).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .jsnum import (
    UNDEFINED, JSInputError, fnum, get, gt0, is_safe_integer, js_ceil, js_locale, js_round,
    js_str, nullish, truthy,
)

ENGINE_VERSION = "calculator_v8"
DATA_DIR = Path(__file__).resolve().parent / "data"

SMALL = "Small container (8 lb / 3.6 kg)"
LARGE = "Large container (40 lb / 18.2 kg)"
_JOINTS = re.compile("joints", re.IGNORECASE | re.ASCII)  # /joints/i


def load_products() -> list[dict]:
    return json.loads((DATA_DIR / "products.json").read_text(encoding="utf-8"))


def load_steps() -> list[dict]:
    return json.loads((DATA_DIR / "steps.json").read_text(encoding="utf-8"))


# ───────── helpers ─────────

def pu(n: Any, u: str) -> str:
    # const pu = (n, u) => (n === 1 ? u : u + 's');
    return u if (n == 1 and not isinstance(n, bool)) else u + "s"


def avg_cov(r: dict) -> Any:
    # if(r.a !== null && r.b !== null && r.a !== undefined && r.b !== undefined) return (r.a + r.b) / 2;
    # return r.b ?? r.a ?? null;
    a, b = get(r, "a"), get(r, "b")
    if not nullish(a) and not nullish(b):
        return (fnum(a) + fnum(b)) / 2
    if not nullish(b):
        return b
    if not nullish(a):
        return a
    return None


def find_joints_rate(prod: dict, group: Any) -> Any:
    # return prod.rates.find(r => r.g === group && /joints/i.test(r.l || '') && r.lf);
    for r in prod["rates"]:
        label = get(r, "l")
        label = label if truthy(label) else ""
        if get(r, "g") == group and _JOINTS.search(js_str(label)) and truthy(get(r, "lf")):
            return r
    return UNDEFINED


def joints_value(S: dict) -> Any:
    # if(S.jointsDirty) return S.joints;
    # return S.area > 0 ? Math.round(S.area * 0.45) : null;
    if truthy(get(S, "jointsDirty")):
        return get(S, "joints")
    area = get(S, "area")
    return js_round(fnum(area) * 0.45) if gt0(area) else None


def openings_value(S: dict) -> Any:
    # return S.openings > 0 ? S.openings : null;
    o = get(S, "openings")
    return o if gt0(o) else None


def has_quantity_override(sid: str) -> bool:
    return sid == "s4" or sid == "s6"


def uses_manual_mesh_qty(row: dict) -> bool:
    return get(row, "pid") in ("p15", "p20", "dmsr")


def _qq(v: Any) -> Any:
    # `v ?? null`
    return None if nullish(v) else v


def eff_qty(S: dict, row: dict) -> Any:
    # if(row.qtyDirty) return row.qty ?? null;
    # if(row.pid === 'gridtape'){ const j = jointsValue(); return j > 0 ? Math.ceil(j / 300) : null; }
    # return row.qty ?? null;
    if truthy(get(row, "qtyDirty")):
        return _qq(get(row, "qty"))
    if get(row, "pid") == "gridtape":
        j = joints_value(S)
        return js_ceil(fnum(j) / 300) if gt0(j) else None
    return _qq(get(row, "qty"))


def _rate_at(rates: list, ri: Any) -> Any:
    # prod.rates[row.ri]  (undefined when out of range or not an index)
    if isinstance(ri, bool):
        return UNDEFINED
    if isinstance(ri, int) or (isinstance(ri, float) and ri.is_integer()):
        i = int(ri)
        if 0 <= i < len(rates):
            return rates[i]
    return UNDEFINED


def _find(items: list, pred) -> Any:
    for it in items:
        if pred(it):
            return it
    return UNDEFINED


# ───────── compute() ─────────

def compute(S: dict, products: list[dict], steps: list[dict]) -> dict:
    if not isinstance(S, dict):
        raise JSInputError("state must be an object")

    def by_id(pid: Any) -> dict:
        # const byId = id => P.find(p => p.id === id);
        p = _find(products, lambda p: p.get("id") == pid)
        if p is UNDEFINED:
            raise JSInputError(f"unknown product id {pid!r}")
        return p

    out: dict[str, Any] = {"lines": [], "errors": {}, "done": {}, "noArea": not gt0(get(S, "area"))}
    if out["noArea"]:
        return out
    area, jl, ol = get(S, "area"), joints_value(S), openings_value(S)
    rows_by_step = get(S, "rows")
    dr = get(S, "dr")
    on = get(S, "on")

    for s in steps:
        sid = s["id"]
        if not truthy(s.get("req", UNDEFINED)) and not truthy(get(on, sid)):
            continue
        errs: list[str] = []
        good = 0

        if truthy(s.get("dualToggle", UNDEFINED)):
            for d in s["dualToggle"]:
                x = get(dr, d["pid"])
                if not truthy(x) or not truthy(get(x, "on")):
                    continue
                if not gt0(get(x, "len")):
                    errs.append("Enter a length for " + js_str(d["label"]) + ".")
                    continue
                prod = by_id(d["pid"])
                rates = prod["rates"]
                out["lines"].append({"sid": sid, "tag": d["label"], "prod": prod,
                                     "rate": rates[0] if rates else UNDEFINED, "lfVal": get(x, "len")})
                good += 1
            out["errors"][sid] = errs
            out["done"][sid] = len(errs) == 0 and good > 0
            continue

        rows = get(rows_by_step, sid)
        if truthy(rows) and not isinstance(rows, list):
            raise JSInputError(f"rows for step {sid} must be a list")
        for row in (rows if truthy(rows) else []):
            if not truthy(get(row, "pid")):
                continue
            prod = by_id(get(row, "pid"))
            if truthy(s.get("directQty", UNDEFINED)) or uses_manual_mesh_qty(row):
                q = eff_qty(S, row)
                if not gt0(q):
                    errs.append("Enter a quantity for " + js_str(prod["name"]) + ".")
                    continue
                out["lines"].append({"sid": sid, "tag": s["name"], "prod": prod, "directQty": q})
                good += 1
                continue
            if prod["id"] == "aqsystem":
                aqW, aqC = get(row, "aqW"), get(row, "aqC")
                if not truthy(aqW) or not truthy(aqC) or not gt0(ol):
                    errs.append("AquaFlash System needs a mesh width, a container and Length of Openings.")
                    continue
                grp = SMALL if aqC == "small" else LARGE
                mesh, liq = by_id("aqflashmesh"), by_id("aqflash")
                w = js_str(aqW)
                out["lines"].append({"sid": sid, "tag": "AquaFlash Mesh", "prod": mesh,
                                     "rate": _find(mesh["rates"], lambda r: get(r, "l") == w + " in wide"),
                                     "lfVal": ol})
                out["lines"].append({"sid": sid, "tag": "AquaFlash Liquid", "prod": liq,
                                     "rate": _find(liq["rates"], lambda r: get(r, "g") == grp and get(r, "l") == w + " in wide mesh"),
                                     "lfVal": ol})
                good += 1
                continue
            if truthy(s.get("epsThickness", UNDEFINED)):
                thick = get(row, "thick")
                if not gt0(thick):
                    errs.append("Enter the insulation thickness for " + js_str(prod["name"]) + ".")
                    continue
                # epsQty: Math.ceil((area / 144) * row.thick)
                out["lines"].append({"sid": sid, "tag": s["name"], "prod": prod,
                                     "epsQty": js_ceil((fnum(area) / 144) * fnum(thick)), "thick": thick})
                good += 1
                continue
            rate = _rate_at(prod["rates"], get(row, "ri"))
            if rate is UNDEFINED:
                rate = prod["rates"][0]  # prod.rates[row.ri] || prod.rates[0]
            if truthy(get(rate, "lf")):
                if not gt0(ol):
                    errs.append("Enter Length of Openings to size " + js_str(prod["name"]) + ".")
                    continue
                out["lines"].append({"sid": sid, "tag": s["name"], "prod": prod, "rate": rate, "lfVal": ol})
            else:
                out["lines"].append({"sid": sid, "tag": s["name"], "prod": prod, "rate": rate, "area": area,
                                     "qtyOverride": get(row, "qty") if has_quantity_override(sid) else None})
            good += 1
            if truthy(s.get("jointsFromGlobal", UNDEFINED)) and truthy(get(rate, "g")) and truthy(get(row, "jt")) and gt0(jl):
                jr = find_joints_rate(prod, get(rate, "g"))
                if truthy(jr):
                    out["lines"].append({"sid": sid, "tag": "Joints (" + js_str(get(rate, "g")) + ")",
                                         "prod": prod, "rate": jr, "lfVal": jl})
        if truthy(s.get("req", UNDEFINED)) and good == 0 and len(errs) == 0:
            errs.append("Choose a product for this step.")
        out["errors"][sid] = errs
        out["done"][sid] = good > 0 and len(errs) == 0
    return out


# ───────── lineInfo() ─────────

def line_info(l: dict, locale: str = "en-IN") -> dict:
    fn = lambda n: js_locale(n, locale)  # const fn = n => Number(n).toLocaleString();
    prod = l["prod"]
    rate = l.get("rate", UNDEFINED)
    # const variant = [l.rate?.g, l.rate?.l].filter(Boolean).join(' — ');
    variant = " — ".join(js_str(v) for v in (get(rate, "g"), get(rate, "l")) if truthy(v))
    qo = l.get("qtyOverride", UNDEFINED)
    if is_safe_integer(qo) and qo > 0:
        return {"units": qo, "unit": pu(qo, prod["unit"]), "cov": "Manual quantity", "variant": variant}
    dq = l.get("directQty", UNDEFINED)
    if not nullish(dq):
        return {"units": dq, "unit": pu(dq, prod["unit"]), "cov": "Entered quantity", "variant": ""}
    eq = l.get("epsQty", UNDEFINED)
    if not nullish(eq):
        return {"units": eq, "unit": pu(eq, prod["unit"]),
                "cov": js_str(l["thick"]) + " in · area ÷ 144 × thickness", "variant": ""}
    lf_val = l.get("lfVal", UNDEFINED)
    if not nullish(lf_val):
        if not truthy(get(rate, "lf")):
            return {"ask": True, "cov": fn(lf_val) + " lin. ft entered", "variant": variant}
        units = js_ceil(fnum(lf_val) / fnum(rate["lf"]))
        return {"units": units, "unit": pu(units, prod["unit"]),
                "cov": fn(rate["lf"]) + " lin. ft per " + js_str(prod["unit"]) + " · " + js_str(prod["ud"]),
                "variant": variant}
    cov = avg_cov(rate)
    if not truthy(cov):
        return {"ask": True, "cov": "Variable coverage", "variant": variant}
    units = js_ceil(fnum(l["area"]) / fnum(cov))
    a, b = get(rate, "a"), get(rate, "b")
    mn = b if nullish(a) else a          # rate.a ?? rate.b
    mx = a if nullish(b) else b          # rate.b ?? rate.a
    unit = js_str(prod["unit"])
    if mn == mx and type(mn) is not bool:  # mn === mx
        lbl = fn(mn) + " sq. ft per " + unit
    elif a is None:                        # rate.a === null (present and null, not missing)
        lbl = "up to " + fn(mx) + " sq. ft per " + unit
    else:
        lbl = fn(mn) + "–" + fn(mx) + " sq. ft per " + unit
    return {"units": units, "unit": pu(units, prod["unit"]), "cov": lbl + " · " + js_str(prod["ud"]), "variant": variant}


def _plain(v: Any) -> Any:
    """Numbers as JavaScript would serialise them (2.0 -> 2)."""
    if isinstance(v, float) and v.is_integer() and abs(v) <= 2**53:
        return int(v)
    return v


def estimate(S: dict, products: list[dict] | None = None, steps: list[dict] | None = None,
             locale: str = "en-IN", include_ids: bool = False) -> dict:
    """compute() + lineInfo() rows, in the same shape the app's review page and exports use.
    include_ids adds each line's step id and product id (used by the calculator screens)."""
    products = products if products is not None else load_products()
    steps = steps if steps is not None else load_steps()
    res = compute(S, products, steps)
    lines = []
    for l in res["lines"]:
        i = line_info(l, locale)
        ask = bool(i.get("ask"))
        line = {
            "layer": l["tag"],
            "product": l["prod"]["name"],
            "variant": i.get("variant") or "",
            "coverage": i.get("cov") or "",
            "units": None if ask else _plain(i.get("units")),
            "unit": i.get("unit") or "",
            "ask": ask,
        }
        if include_ids:
            line["sid"] = l["sid"]
            line["pid"] = l["prod"]["id"]
        lines.append(line)
    jv = joints_value(S)
    return {
        "engine_version": ENGINE_VERSION,
        "locale": locale,
        "noArea": res["noArea"],
        "joints": None if nullish(jv) else _plain(jv),
        "lines": lines,
        "errors": res["errors"],
        "done": res["done"],
    }
