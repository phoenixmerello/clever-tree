"""legislation.gov.uk lookup: confirm an Act the AI names really exists, and get its real URL.

Search feed: https://www.legislation.gov.uk/search/data.feed?title=<title>   (Atom XML)
Entry <id> looks like http://www.legislation.gov.uk/id/ukpga/2015/15 -> web URL /ukpga/2015/15
A section link is only returned if /section/N/data.xml actually exists.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

BASE = "https://www.legislation.gov.uk"
ATOM = "{http://www.w3.org/2005/Atom}"
TIMEOUT = 8


def _get(url: str, params: dict | None = None) -> tuple[int, str]:
    """Single HTTP entry point (tests replace this)."""
    r = httpx.get(url, params=params, timeout=TIMEOUT, follow_redirects=True,
                  headers={"User-Agent": "legal-access-hackathon/1.0"})
    return r.status_code, r.text


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def find_act(title: str, year: int | str | None = None, section: str | None = None) -> dict | None:
    """-> {'title','url','section','section_url'} or None if it can't be verified."""
    title = (title or "").strip()
    if not title:
        return None
    m = re.search(r"\b(1[6-9]\d\d|20\d\d)\b", title)
    year = str(year or (m.group(1) if m else "")).strip()
    bare = re.sub(r"\s*\b(1[6-9]\d\d|20\d\d)\b\s*$", "", title).strip()
    # Narrow lookup first: Acts of that year whose title matches (e.g. /ukpga/2004/data.feed?title=Housing Act)
    urls = ([f"{BASE}/ukpga/{year}/data.feed"] if year else []) + [f"{BASE}/search/data.feed"]
    root = None
    for url in urls:
        try:
            status, xml = _get(url, {"title": bare})
            if status != 200:
                continue
            root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
            if _match(root, bare, year):
                break
        except Exception as e:
            print(f"[legislation] lookup failed for {title!r} at {url}: {e}")
    if root is None:
        return None
    return _match(root, bare, year, section)


def _match(root, bare: str, year: str, section: str | None = None) -> dict | None:
    want = _norm(f"{bare} {year}" if year else bare)
    for entry in root.iter(f"{ATOM}entry"):
        etitle = (entry.findtext(f"{ATOM}title") or "").strip()
        eid = (entry.findtext(f"{ATOM}id") or "").strip()
        if not eid or "/id/" not in eid:
            continue
        nt = _norm(etitle)
        if nt == want or (not year and nt.startswith(want)):
            path = eid.split("legislation.gov.uk", 1)[1].replace("/id/", "/", 1)
            out = {"title": etitle, "url": f"{BASE}{path}", "section": None, "section_url": None}
            sec = str(section or "").strip().lower().removeprefix("section").strip()
            if sec and re.fullmatch(r"\d+[a-z]{0,2}", sec) and "/ukpga/" in path:
                try:
                    s_status, _ = _get(f"{BASE}{path}/section/{sec}/data.xml")
                    if s_status == 200:
                        out["section"] = sec
                        out["section_url"] = f"{BASE}{path}/section/{sec}"
                except Exception:
                    pass
            return out
    return None
