"""
Golden-output checks for the regression suite.

    check("f1_price_race", obj)

compares `obj` (numbers, strings, lists, dicts, DataFrames) with tests/golden/<name>.json
to a tight tolerance. To bless an intended change:

    UPDATE_GOLDEN=1 python -m pytest            (then review `git diff tests/golden`)

A missing golden file is written on first run (and the test passes with a note).
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

GOLDEN = Path(__file__).resolve().parent / "golden"
REL, ABS = 1e-6, 1e-9


def canon(obj):
    """JSON-able, order-stable version of obj (floats to 10 significant digits)."""
    if isinstance(obj, pd.DataFrame):
        return [canon(r) for r in obj.to_dict("records")]
    if isinstance(obj, pd.Series):
        return canon(obj.to_dict())
    if isinstance(obj, dict):
        return {str(k): canon(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [canon(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        if math.isnan(obj):
            return None
        return float(f"{float(obj):.10g}")
    if obj is None or (not isinstance(obj, str) and pd.isna(obj)):
        return None
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(obj))
    return str(obj)


def _diff(a, b, path="$"):
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return f"{path}: keys differ: missing {sorted(set(b) - set(a))[:5]}, extra {sorted(set(a) - set(b))[:5]}"
        for k in a:
            d = _diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != golden {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return None if a is b else f"{path}: {a} != golden {b}"
        return None if math.isclose(a, b, rel_tol=REL, abs_tol=ABS) else f"{path}: {a!r} != golden {b!r}"
    return None if a == b else f"{path}: {a!r} != golden {b!r}"


def check(name, obj):
    got = canon(obj)
    f = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_GOLDEN") or not f.exists():
        GOLDEN.mkdir(exist_ok=True)
        f.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
        return
    want = json.loads(f.read_text())
    d = _diff(got, want)
    if d:
        pytest.fail(f"{name} changed: {d}\n(if intended: UPDATE_GOLDEN=1 python -m pytest, then review git diff tests/golden)")
