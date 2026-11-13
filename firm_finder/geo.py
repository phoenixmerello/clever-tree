"""Postcode -> lat/lng via postcodes.io (free, no key). Results cached in memory."""
from __future__ import annotations

import math

import httpx

API = "https://api.postcodes.io"
_cache: dict[str, tuple[float, float] | None] = {}

# Offline fallback so the demo works without internet (Leeds-area outcodes)
_OUTCODE_FALLBACK = {
    "LS1": (53.797, -1.548), "LS2": (53.803, -1.546), "LS3": (53.801, -1.564),
    "LS6": (53.818, -1.574), "LS7": (53.820, -1.535), "LS9": (53.797, -1.513),
    "LS10": (53.770, -1.535), "LS11": (53.781, -1.555), "LS12": (53.790, -1.588),
    "LS17": (53.857, -1.523), "LS27": (53.745, -1.600), "LS28": (53.807, -1.664),
    "BD1": (53.794, -1.752), "WF1": (53.683, -1.497), "HG1": (53.993, -1.538),
    "YO1": (53.959, -1.082), "M1": (53.479, -2.237), "M2": (53.481, -2.244),
    "S1": (53.381, -1.470), "HX1": (53.722, -1.858), "HD1": (53.646, -1.784),
    "EC2A": (51.522, -0.081), "B3": (52.481, -1.902), "B4": (52.483, -1.893),
    "LS4": (53.811, -1.582), "LS5": (53.818, -1.600), "LS8": (53.823, -1.512), "LS16": (53.851, -1.590),
    "M3": (53.483, -2.252), "M4": (53.484, -2.230), "NE1": (54.971, -1.613), "L2": (53.407, -2.990),
    "L3": (53.410, -2.985), "NG1": (52.954, -1.149), "S3": (53.388, -1.476), "EC1Y": (51.523, -0.090),
    "EC1N": (51.519, -0.109), "EC2M": (51.517, -0.081), "EC3M": (51.512, -0.080), "W1J": (51.507, -0.143),
}


def _norm(pc: str) -> str:
    return "".join(pc.upper().split())


def _fallback(pc: str):
    p = _norm(pc)
    out = p[:-3] if len(p) > 4 else p
    return _OUTCODE_FALLBACK.get(out)


def lookup(postcode: str) -> tuple[float, float] | None:
    p = _norm(postcode)
    if p in _cache:
        return _cache[p]
    res = None
    try:
        url = f"{API}/postcodes/{p}" if len(p) > 4 else f"{API}/outcodes/{p}"
        r = httpx.get(url, timeout=5)
        if r.status_code == 200:
            j = r.json()["result"]
            res = (j["latitude"], j["longitude"])
    except Exception:
        pass
    _cache[p] = res or _fallback(p)
    return _cache[p]


def bulk(postcodes: list[str]) -> None:
    """Warm the cache for many postcodes at once (100 per request)."""
    todo = list({_norm(p) for p in postcodes if p and _norm(p) not in _cache})
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        try:
            r = httpx.post(f"{API}/postcodes", json={"postcodes": chunk}, timeout=10)
            for item in r.json()["result"]:
                q, res = _norm(item["query"]), item["result"]
                _cache[q] = (res["latitude"], res["longitude"]) if res else _fallback(q)
        except Exception:
            for q in chunk:
                _cache[q] = _fallback(q)


def miles(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))
