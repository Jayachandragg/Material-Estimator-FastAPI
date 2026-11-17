"""Proves the Python engine gives exactly the same results as calculator_v8.html.

tests/cases.jsonl is produced by tools/make_cases.mjs, which runs the ORIGINAL JavaScript
calculator and records its output. Every field must match exactly: quantities, units, product
names, variants, coverage text, error messages and step status.
"""
import json
from pathlib import Path

import pytest

from app.engine import estimate, load_products, load_steps

CASES = Path(__file__).parent / "cases.jsonl"
FIELDS = ("noArea", "joints", "lines", "errors", "done")


@pytest.mark.skipif(not CASES.exists(), reason="run `node tools/make_cases.mjs` first")
def test_python_matches_javascript_exactly():
    products, steps = load_products(), load_steps()
    total = lines = 0
    failures = []
    with CASES.open(encoding="utf-8") as f:
        for raw in f:
            case = json.loads(raw)
            got = estimate(case["state"], products, steps, case["locale"])
            exp = case["expected"]
            total += 1
            lines += len(exp["lines"])
            for k in FIELDS:
                if got[k] != exp[k]:
                    failures.append((case["id"], case["locale"], k, exp[k], got[k]))
                    break
    print(f"\nparity: {total} cases, {lines} material lines, {len(failures)} differences")
    assert total > 0
    assert not failures, "\n".join(f"{i} [{loc}] {k}:\n  JS: {e}\n  PY: {g}" for i, loc, k, e, g in failures[:5])
