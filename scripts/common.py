"""Shared helpers for the validation scripts (standard library only). From the defence kit, Part 9."""

import json
import statistics
import time
import urllib.error
import urllib.request


def http(method, url, body=None, headers=None, timeout=30):
    """Return (status, parsed_json_or_text, elapsed_seconds). Never raises on HTTP errors."""
    data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return 0, str(e), time.perf_counter() - start
    elapsed = time.perf_counter() - start
    try:
        return status, json.loads(raw or b"null"), elapsed
    except ValueError:
        return status, raw.decode(errors="replace"), elapsed


def pick(d, *keys, default=None):
    """First present key (dotted paths allowed)."""
    for k in keys:
        cur = d
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                break
        else:
            return cur
    return default


def pct(values, p):
    """Nearest-rank percentile (p in 0..100)."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(p / 100 * len(s) + 0.5)) - 1))
    return s[k]


def summary(name, values, unit="s"):
    if not values:
        return f"{name}: no samples"
    return (
        f"{name}: n={len(values)} min={min(values):.3f}{unit} p50={pct(values, 50):.3f}{unit} "
        f"p95={pct(values, 95):.3f}{unit} max={max(values):.3f}{unit} "
        f"mean={statistics.mean(values):.3f}{unit}"
    )


def write_report(path, lines):
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n[report written to {path}]")
