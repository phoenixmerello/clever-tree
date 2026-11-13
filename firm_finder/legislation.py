"""legislation.gov.uk: confirm Acts/Regulations really exist, get real URLs, and read section text.

Lookups (official API, no key):
  /ukpga/<year>/data.feed?title=...   Acts of that year whose title matches (Atom)
  /uksi/<year>/data.feed?title=...    Statutory Instruments (e.g. Regulations)
  /search/data.feed?title=...         fallback
  <act>/section/<n>/data.xml          a section's text (CLML XML)
Nothing is shown unless it was found on legislation.gov.uk.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import httpx

BASE = "https://www.legislation.gov.uk"
ATOM = "{http://www.w3.org/2005/Atom}"
TIMEOUT = 8
SECTION_CHARS = 1800
_YEAR = re.compile(r"\b(1[6-9]\d\d|20\d\d)\b")


def _get(url: str, params: dict | None = None) -> tuple[int, str]:
    """Single HTTP entry point (tests replace this)."""
    r = httpx.get(url, params=params, timeout=TIMEOUT, follow_redirects=True,
                  headers={"User-Agent": "legal-access-hackathon/1.0"})
    return r.status_code, r.text


def _norm(s: str) -> str:
    out = " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())
    return out[4:] if out.startswith("the ") else out


def section_text(xml: str) -> str:
    """Plain text of a section from its CLML data.xml (headings + text, metadata excluded)."""
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except Exception:
        return ""
    chunks: list[str] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] in ("Title", "Text"):
            t = " ".join("".join(el.itertext()).split())
            if t and t not in chunks[-1:]:
                chunks.append(t)
    return "\n".join(chunks)[:SECTION_CHARS]


def _split(title: str, year) -> tuple[str, str]:
    title = (title or "").strip()
    m = _YEAR.search(title)
    year = str(year or (m.group(1) if m else "")).strip()
    bare = _YEAR.sub("", title).strip().rstrip(",").strip()
    return bare, year


def _match_feed(xml: str, bare: str, year: str) -> tuple[str, str] | None:
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except Exception:
        return None
    want = _norm(f"{bare} {year}" if year else bare)
    for entry in root.iter(f"{ATOM}entry"):
        etitle = (entry.findtext(f"{ATOM}title") or "").strip()
        eid = (entry.findtext(f"{ATOM}id") or "").strip()
        if not eid or "/id/" not in eid:
            continue
        nt = _norm(etitle)
        if nt == want or (not year and nt.startswith(want)):
            return etitle, eid.split("legislation.gov.uk", 1)[1].replace("/id/", "/", 1)
    return None


@lru_cache(maxsize=256)
def locate(bare: str, year: str) -> tuple[str, str] | None:
    """-> (official title, path like /ukpga/1996/18) or None."""
    if not bare:
        return None
    urls = ([f"{BASE}/ukpga/{year}/data.feed", f"{BASE}/uksi/{year}/data.feed"] if year else []) \
        + [f"{BASE}/search/data.feed"]
    for url in urls:
        try:
            status, xml = _get(url, {"title": bare})
        except Exception as e:
            print(f"[legislation] lookup failed for {bare!r} at {url}: {e}")
            continue
        if status == 200:
            hit = _match_feed(xml, bare, year)
            if hit:
                return hit
    return None


def _section(path: str, sec: str) -> dict | None:
    sec = str(sec or "").strip().lower().removeprefix("section").removeprefix("s.").strip()
    if not (sec and re.fullmatch(r"\d+[a-z]{0,2}", sec) and "/ukpga/" in path):
        return None
    try:
        status, xml = _get(f"{BASE}{path}/section/{sec}/data.xml")
    except Exception:
        return None
    if status != 200:
        return None
    return {"section": sec, "section_url": f"{BASE}{path}/section/{sec}", "section_text": section_text(xml)}


def find_act(title: str, year=None, section: str | None = None) -> dict | None:
    """One Act (+ optional one section). -> {'title','url','section','section_url','section_text'} or None."""
    bare, year = _split(title, year)
    hit = locate(bare, year)
    if not hit:
        return None
    etitle, path = hit
    out = {"title": etitle, "url": f"{BASE}{path}", "section": None, "section_url": None, "section_text": ""}
    s = _section(path, section) if section else None
    if s:
        out.update(s)
    return out


def resolve(laws: list[dict], max_acts: int = 3, max_sections: int = 5) -> list[dict]:
    """laws: [{'title','year','sections':[...]}] -> verified items, one per section (or per Act if none).
    Duplicates (same Act from topics + AI) are merged."""
    acts: dict[str, dict] = {}
    for l in laws:
        bare, year = _split(l.get("title", ""), l.get("year"))
        key = f"{_norm(bare)}|{year}"
        if not bare:
            continue
        a = acts.setdefault(key, {"bare": bare, "year": year, "sections": []})
        for s in l.get("sections") or []:
            if str(s) not in a["sections"]:
                a["sections"].append(str(s))
    acts_list = list(acts.values())[:max_acts]

    with ThreadPoolExecutor(max_workers=4) as ex:
        located = list(ex.map(lambda a: locate(a["bare"], a["year"]), acts_list))
    jobs, out = [], []
    for a, hit in zip(acts_list, located):
        if not hit:
            continue
        etitle, path = hit
        if not a["sections"]:
            out.append({"title": etitle, "url": f"{BASE}{path}", "section": None, "section_url": None,
                        "section_text": ""})
        for s in a["sections"]:
            if len(jobs) < max_sections:
                jobs.append((etitle, path, s))
    with ThreadPoolExecutor(max_workers=5) as ex:
        secs = list(ex.map(lambda j: _section(j[1], j[2]), jobs))
    ok_paths = {j[1] for j, s in zip(jobs, secs) if s}
    for (etitle, path, _), s in zip(jobs, secs):
        if s:
            out.append({"title": etitle, "url": f"{BASE}{path}", **s})
        elif path not in ok_paths:              # no section verified -> still link the Act once
            ok_paths.add(path)
            out.append({"title": etitle, "url": f"{BASE}{path}", "section": None, "section_url": None,
                        "section_text": ""})
    return out
