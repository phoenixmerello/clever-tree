"""SRA register data: download once a day, cache to disk, search locally.

Official API (free key): register at https://sra-prod-apim.developer.azure-api.net
-> Products -> Datasharing -> 'SRA Data Share API Version V1' -> Subscribe -> Profile -> key.
Set SRA_API_KEY in your .env.

The normaliser below is deliberately tolerant of field-name differences, because
we couldn't hit the live API from the build box. If the live JSON uses different
keys, adjust _pick() calls in _normalise_org / _normalise_office only.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx

from .areas import canonical

SRA_BASE = os.getenv("SRA_API_BASE", "https://sra-prod-apim.azure-api.net/datashare/api/V1")
CACHE = Path(os.getenv("SRA_CACHE", "cache/sra_orgs.json"))
DEMO = Path(__file__).resolve().parent.parent / "demo_data" / "sra_demo.json"
CACHE_TTL = 24 * 3600  # SRA updates every 24h


def _pick(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _normalise_office(o: dict) -> dict:
    addr = [_pick(o, f"Address{i}", f"AddressLine{i}") for i in range(1, 6)]
    return {
        "name": _pick(o, "Name", "OfficeName"),
        "type": _pick(o, "OfficeType", "Type"),  # head office / branch
        "address": ", ".join(a for a in addr if a),
        "town": _pick(o, "Town", "City"),
        "postcode": (_pick(o, "Postcode", "PostCode", default="") or "").upper().strip(),
        "phone": _pick(o, "PhoneNumber", "Telephone", "Phone"),
        "email": _pick(o, "Email", "EmailAddress"),
        "website": _pick(o, "Website", "WebsiteAddress", "Url"),
    }


def _normalise_org(o: dict) -> dict:
    raw_areas = _pick(o, "WorkArea", "WorkAreas", "AreasOfLaw", default=[]) or []
    if isinstance(raw_areas, str):
        raw_areas = [raw_areas]
    areas = sorted({c for a in raw_areas if (c := canonical(str(a)))})
    offices = [_normalise_office(x) for x in (_pick(o, "Offices", "Office", default=[]) or [])]
    return {
        "sra_number": str(_pick(o, "SraNumber", "SRANumber", "OrganisationId", "Id", default="")),
        "name": _pick(o, "PracticeName", "Name", "OrganisationName"),
        "trading_names": _pick(o, "TradingNames", default=[]) or [],
        "status": _pick(o, "AuthorisationStatus", "Status", default=""),
        "type": _pick(o, "AuthorisationType", "OrganisationType", "Type", default=""),
        "work_areas": areas,
        "offices": [x for x in offices if x["postcode"]],
        "register_url": f"https://www.sra.org.uk/consumers/register/organisation/?sraNumber="
                        f"{_pick(o, 'SraNumber', 'SRANumber', default='')}",
    }


def _is_active(org: dict) -> bool:
    s = (org["status"] or "").lower()
    return (not s) or ("authoris" in s and "revok" not in s and "suspend" not in s)


XLSX = Path(os.getenv("FIRMS_XLSX", Path(__file__).resolve().parent.parent / "data" / "firms.xlsx"))

# header aliases -> internal field (lower-case, stripped)
_COLS = {
    "sra": ["sra number", "sra no", "sra"],
    "name": ["name", "firm name", "firm"],
    "address": ["address"],
    "city": ["city", "town"],
    "postcode": ["postcode", "post code"],
    "phone": ["phone number", "phone", "telephone"],
    "email": ["email"],
    "website": ["website", "url"],
    "areas": ["practice area", "practice areas", "areas of law", "work areas"],
}
_PC = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)


def load_xlsx(path: Path) -> list[dict]:
    """Read the team's spreadsheet. One row per office; same SRA number = same firm.
    Practice-area labels are kept exactly as written - the AI classifies into whatever
    labels the sheet uses, so no mapping to SRA wording is needed."""
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    norm = lambda v: " ".join(str(v or "").lower().split())
    hdr_i = next(i for i, r in enumerate(rows) if r and any(norm(c) in _COLS["sra"] for c in r))
    hdr = [norm(c) for c in rows[hdr_i]]
    idx = {k: next((hdr.index(a) for a in al if a in hdr), None) for k, al in _COLS.items()}
    get = lambda r, k: ("" if idx[k] is None or idx[k] >= len(r) or r[idx[k]] is None
                        else " ".join(str(r[idx[k]]).split()))

    merged: dict[str, dict] = {}
    for r in rows[hdr_i + 1:]:
        name = get(r, "name")
        if not name or "example row" in name.lower():
            continue
        raw_sra = get(r, "sra").removesuffix(".0")
        digits = re.search(r"\d{5,7}", raw_sra)
        sra_no = digits.group(0) if digits else ""
        address = get(r, "address")
        pc = get(r, "postcode") or ((m := _PC.search(address)) and m.group(1).upper()) or ""
        areas = [" ".join(a.split()) for a in get(r, "areas").split(";") if a.strip()]
        office = {"name": name, "type": "", "address": address, "town": get(r, "city"),
                  "postcode": pc.upper(), "phone": get(r, "phone"), "email": get(r, "email"),
                  "website": get(r, "website")}
        key = sra_no or name.lower()
        if key not in merged:
            merged[key] = {
                "sra_number": sra_no, "name": name, "trading_names": [], "status": "", "type": "",
                "work_areas": [], "offices": [],
                "sra_needs_check": raw_sra != sra_no,  # sheet flagged it e.g. '(verify - see Notes)'
                "register_url": "https://www.sra.org.uk/consumers/register/"
                                + (f"organisation/?sraNumber={sra_no}" if sra_no else ""),
            }
        f = merged[key]
        f["offices"].append(office)
        f["work_areas"] = sorted(set(f["work_areas"]) | set(areas))
        f["sra_needs_check"] = f["sra_needs_check"] or raw_sra != sra_no
    return [o for o in merged.values() if o["work_areas"]]


def load_orgs(force_refresh: bool = False) -> tuple[list[dict], str]:
    """Returns (orgs, source): 'spreadsheet', 'sra-live', 'sra-cache' or 'demo'."""
    if XLSX.exists():
        return load_xlsx(XLSX), "spreadsheet"
    key = os.getenv("SRA_API_KEY")
    if key:
        fresh = CACHE.exists() and time.time() - CACHE.stat().st_mtime < CACHE_TTL
        if fresh and not force_refresh:
            return json.loads(CACHE.read_text()), "sra-cache"
        try:
            r = httpx.get(f"{SRA_BASE}/organisation/GetAll",
                          headers={"Ocp-Apim-Subscription-Key": key}, timeout=120)
            r.raise_for_status()
            data = r.json()
            raw = data.get("Organisations", data) if isinstance(data, dict) else data
            orgs = [n for n in (_normalise_org(o) for o in raw) if _is_active(n) and n["work_areas"]]
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(json.dumps(orgs))
            return orgs, "sra-live"
        except Exception as e:  # fall back to stale cache, then demo
            print(f"[sra] live fetch failed: {e}")
            if CACHE.exists():
                return json.loads(CACHE.read_text()), "sra-cache"
    return json.loads(DEMO.read_text()), "demo"


def candidates(orgs: list[dict], areas: list[str]) -> list[dict]:
    """All authorised firms that report at least one of the needed areas."""
    wanted = set(areas)
    return [o for o in orgs if wanted & set(o["work_areas"])]
