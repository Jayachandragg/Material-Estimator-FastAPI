"""JavaScript number semantics, reproduced exactly in Python.

The verified calculator is JavaScript. Python differs in a few places that would change results or
labels, so each one is reproduced here:

- Math.round rounds .5 up (toward +infinity); Python's round() rounds .5 to even.
- String(number) prints 2 for 2.0 and 1e-7 for 0.0000001; Python prints 2.0 and 1e-07.
- Number.prototype.toLocaleString() groups digits by locale and keeps at most 3 decimals,
  rounding the shortest decimal form half away from zero (1.0005 -> "1.001").
- JavaScript "truthiness": [] and {} are true; 0, NaN, "" and null are false.
- JavaScript has two empty values, null and undefined. UNDEFINED stands for a missing key.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any


class _Undefined:
    """JavaScript `undefined` (a key that is not present)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "undefined"

    def __bool__(self) -> bool:
        return False


UNDEFINED = _Undefined()
MAX_SAFE_INTEGER = 2**53 - 1


class JSInputError(ValueError):
    """Input the browser calculator could never produce (e.g. text where a number belongs)."""


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def nullish(v: Any) -> bool:
    """`v == null` in JavaScript: null or undefined."""
    return v is None or v is UNDEFINED


def get(obj: Any, key: str) -> Any:
    """obj.key / obj?.key: UNDEFINED when the object or key is missing."""
    if isinstance(obj, dict):
        return obj.get(key, UNDEFINED)
    return UNDEFINED


def truthy(v: Any) -> bool:
    if v is None or v is UNDEFINED or v is False:
        return False
    if v is True:
        return True
    if is_number(v):
        return not (v == 0 or (isinstance(v, float) and math.isnan(v)))
    if isinstance(v, str):
        return v != ""
    return True  # objects and arrays, even empty ones


def gt0(v: Any) -> bool:
    """`v > 0` for the values the calculator stores: numbers, null or undefined."""
    if v is None:
        return False  # null > 0 -> 0 > 0
    if v is UNDEFINED:
        return False  # undefined > 0 -> NaN > 0
    if is_number(v):
        return v > 0
    raise JSInputError(f"expected a number or null, got {type(v).__name__}: {v!r}")


def fnum(v: Any) -> float:
    """A number as an IEEE double, like every JavaScript number."""
    if not is_number(v):
        raise JSInputError(f"expected a number, got {type(v).__name__}: {v!r}")
    return float(v)


def js_round(x: float) -> int:
    """Math.round: nearest integer, ties toward +infinity."""
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


def js_ceil(x: float) -> int:
    return math.ceil(x)


def is_safe_integer(v: Any) -> bool:
    """Number.isSafeInteger."""
    if not is_number(v):
        return False
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v) or not v.is_integer()):
        return False
    return abs(v) <= MAX_SAFE_INTEGER


def _shortest_digits(x: float) -> tuple[str, int]:
    """Shortest round-trip decimal digits of a positive finite double, and the decimal point
    position n, so that x = 0.DIGITS x 10^n. Python's repr and JavaScript use the same shortest form."""
    sign, digits, exp = Decimal(repr(x)).as_tuple()
    ds = "".join(map(str, digits)).lstrip("0") or "0"
    # remove trailing zeros, moving them into the exponent
    stripped = ds.rstrip("0")
    exp += len(ds) - len(stripped)
    ds = stripped or "0"
    n = exp + len(ds)
    return ds, n


def js_str(v: Any) -> str:
    """String(v) / `'' + v` in JavaScript."""
    if isinstance(v, str):
        return v
    if v is None:
        return "null"
    if v is UNDEFINED:
        return "undefined"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if is_number(v):
        x = float(v)
        if math.isnan(x):
            return "NaN"
        if math.isinf(x):
            return "Infinity" if x > 0 else "-Infinity"
        if x == 0:
            return "0"
        if x < 0:
            return "-" + js_str(-x)
        ds, n = _shortest_digits(x)
        k = len(ds)
        if k <= n <= 21:
            return ds + "0" * (n - k)
        if 0 < n <= 21:
            return ds[:n] + "." + ds[n:]
        if -6 < n <= 0:
            return "0." + "0" * (-n) + ds
        e = n - 1
        es = ("+" if e >= 0 else "-") + str(abs(e))
        return (ds + "e" + es) if k == 1 else (ds[0] + "." + ds[1:] + "e" + es)
    raise JSInputError(f"cannot convert {type(v).__name__} to text")


def _group(int_digits: str, locale: str) -> str:
    if locale == "en-IN":
        if len(int_digits) <= 3:
            return int_digits
        head, tail = int_digits[:-3], int_digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        return ",".join(parts + [tail])
    # en-US
    parts = []
    while len(int_digits) > 3:
        parts.insert(0, int_digits[-3:])
        int_digits = int_digits[:-3]
    parts.insert(0, int_digits)
    return ",".join(parts)


SUPPORTED_LOCALES = ("en-IN", "en-US")


def js_locale(v: Any, locale: str = "en-IN") -> str:
    """Number(v).toLocaleString() as a browser set to `locale` shows it."""
    if locale not in SUPPORTED_LOCALES:
        raise JSInputError(f"unsupported locale {locale!r}; use one of {SUPPORTED_LOCALES}")
    if v is None:
        x = 0.0  # Number(null) -> 0
    elif v is UNDEFINED:
        x = math.nan
    elif is_number(v):
        x = float(v)
    else:
        raise JSInputError(f"expected a number, got {type(v).__name__}")
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return ("-" if x < 0 else "") + "∞"
    negative = x < 0 or (x == 0 and math.copysign(1.0, x) < 0)
    a = abs(x)
    if a == 0:
        rounded = Decimal(0)
    else:
        with localcontext() as ctx:
            ctx.prec = 400
            rounded = Decimal(repr(a)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    int_part, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    out = _group(int_part, locale) + ("." + frac if frac else "")
    return ("-" if negative else "") + out
