"""GOV.UK retrieval via the official public APIs (no key needed).

Search:  https://www.gov.uk/api/search.json?q=...
Content: https://www.gov.uk/api/content/<path>   (guides -> details.parts[{slug,title,body}])

The code fetches pages; the AI only ever reads what we fetched. Nothing is browsed freely.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser

import httpx

BASE = "https://www.gov.uk"
TIMEOUT = 8

# Citizen-facing guidance only (no news, speeches, stats, consultations...)
ALLOWED_TYPES = {"guide", "answer", "transaction", "detailed_guide", "local_transaction"}
MAX_PAGES = 4
SECTION_CHARS = 2500
TOTAL_CHARS = 40_000


def _get_json(url: str, params: dict | None = None) -> dict:
    """Single HTTP entry point (tests replace this)."""
    r = httpx.get(url, params=params, timeout=TIMEOUT, follow_redirects=True,
                  headers={"User-Agent": "legal-access-hackathon/1.0"})
    r.raise_for_status()
    return r.json()


class _Text(HTMLParser):
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "br", "div", "tr", "dt", "dd", "section", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(html: str) -> tuple[str, list[str]]:
    p = _Text()
    p.feed(html or "")
    lines = [" ".join(l.split()) for l in unescape("".join(p.parts)).split("\n")]
    return "\n".join(l for l in lines if l), p.links


def search(queries: list[str]) -> list[dict]:
    """Run each query, interleave results (rank-fair), keep citizen guidance, dedupe."""
    per_query: list[list[dict]] = []
    fields = ["title", "description", "link", "format", "content_store_document_type"]
    for q in [q for q in queries if q and q.strip()][:3]:
        try:
            res = _get_json(f"{BASE}/api/search.json", {"q": q, "count": 8, "fields": fields}).get("results", [])
        except Exception as e:
            print(f"[govuk] search failed for {q!r}: {e}")
            res = []
        per_query.append(res)
    seen, out = set(), []
    for i in range(max((len(r) for r in per_query), default=0)):
        for res in per_query:
            if i >= len(res):
                continue
            item = res[i]
            link = item.get("link") or ""
            dtype = item.get("content_store_document_type") or item.get("format")
            if not link.startswith("/") or link in seen or dtype not in ALLOWED_TYPES:
                continue
            seen.add(link)
            out.append({"title": item.get("title", ""), "link": link,
                        "description": item.get("description", ""), "type": dtype})
    return out


def _details_html(details: dict) -> list[tuple[str, str, str]]:
    """-> [(slug, title, html)] for any GOV.UK schema we accept."""
    if details.get("parts"):
        return [(p.get("slug", ""), p.get("title", ""), p.get("body", "")) for p in details["parts"]]
    chunks = []
    for key in ("introductory_paragraph", "introduction", "body", "more_information",
                "need_to_know", "what_you_need_to_know", "other_ways_to_apply"):
        v = details.get(key)
        if isinstance(v, list):  # multi-content-type form: [{content_type, content}]
            v = next((x.get("content") for x in v if x.get("content_type") == "text/html"), "")
        if isinstance(v, str) and v.strip():
            chunks.append(v)
    return [("", "", "\n".join(chunks))] if chunks else []


def fetch_page(link: str) -> dict | None:
    try:
        j = _get_json(f"{BASE}/api/content{link}")
    except Exception as e:
        print(f"[govuk] content failed for {link}: {e}")
        return None
    base_path = j.get("base_path") or link
    page_url = f"{BASE}{base_path}"
    sections, leg_links = [], []
    for i, (slug, title, html) in enumerate(_details_html(j.get("details") or {})):
        text, links = html_to_text(html)
        if not text:
            continue
        leg_links += [l for l in links if "legislation.gov.uk" in l]
        url = page_url if (i == 0 or not slug) else f"{page_url}/{slug}"
        sections.append({"title": title or j.get("title", ""), "url": url, "text": text})
    if not sections:
        return None
    return {"title": j.get("title", ""), "url": page_url, "sections": sections,
            "legislation_links": sorted(set(leg_links)),
            "updated": j.get("public_updated_at")}


def retrieve(queries: list[str], known_paths: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """Known topic pages first (reliable), then search results; -> (pages, sections S1..Sn)."""
    links = list(dict.fromkeys(known_paths or []))
    if len(links) < MAX_PAGES:
        links += [h["link"] for h in search(queries) if h["link"] not in links]
    links = links[:MAX_PAGES]
    with ThreadPoolExecutor(max_workers=MAX_PAGES) as ex:
        pages = [p for p in ex.map(fetch_page, links) if p]
    sections, budget = [], TOTAL_CHARS
    for p in pages:
        for s in p["sections"]:
            if budget <= 0:
                break
            text = s["text"][:min(SECTION_CHARS, budget)]
            budget -= len(text)
            sections.append({"id": f"S{len(sections) + 1}", "page_title": p["title"],
                             "section_title": s["title"], "url": s["url"], "text": text})
    return pages, sections
