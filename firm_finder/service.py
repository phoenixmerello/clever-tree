"""The pipeline: problem -> triage -> SRA filter -> score -> LLM rerank -> cards for the UI."""
from __future__ import annotations

from . import ai, geo, sra

_ORGS: list[dict] | None = None
_SOURCE = ""


def _orgs():
    global _ORGS, _SOURCE
    if _ORGS is None:
        _ORGS, _SOURCE = sra.load_orgs()
    return _ORGS


def practice_areas() -> list[str]:
    """Every practice-area label present in the loaded data (the AI's vocabulary)."""
    return sorted({a for o in _orgs() for a in o["work_areas"]})


def run_triage(problem: str, user_type: str = "individual", category: str | None = None) -> dict:
    return ai.classify(problem, practice_areas(), user_type, category)


FALLBACK_LINKS = [
    {"label": "Law Society - Find a Solicitor", "url": "https://solicitors.lawsociety.org.uk/"},
    {"label": "SRA register of solicitors and firms", "url": "https://www.sra.org.uk/consumers/register/"},
    {"label": "Find a legal aid adviser (GOV.UK)", "url": "https://www.gov.uk/check-legal-aid"},
]


def _score(org: dict, primary: str, secondary: list[str], dist: float | None, max_miles: float) -> float:
    s = 0.0
    areas = set(org["work_areas"])
    if primary in areas:
        s += 50
    s += 10 * len(areas & set(secondary))
    # specialism: matching firms that list fewer areas are more focused
    s += max(0, 15 - len(areas))
    if dist is not None:
        s += max(0, 25 * (1 - dist / max_miles))
    return s


def recommend(problem: str, user_type: str = "individual", postcode: str | None = None,
              category: str | None = None, max_miles: float = 25, remote_ok: bool = False,
              top_n: int = 5, triage: dict | None = None) -> dict:
    t = triage or run_triage(problem, user_type, category)
    primary, secondary = t["primary_area"], t.get("secondary_areas", [])
    if primary == ai.NO_MATCH:
        return _no_match(t, "None of the firms in our directory list this area of law.")

    cands = sra.candidates(_orgs(), [primary, *secondary])
    # must cover the primary need if any firm does
    prim = [c for c in cands if primary in c["work_areas"]]
    cands = prim or cands

    here = geo.lookup(postcode) if postcode else None
    if here:
        geo.bulk([o["postcode"] for c in cands for o in c["offices"]])

    scored = []
    for c in cands:
        best, dist = None, None
        if here:
            for o in c["offices"]:
                p = geo.lookup(o["postcode"])
                if p:
                    d = geo.miles(here, p)
                    if dist is None or d < dist:
                        best, dist = o, d
            if not remote_ok and (dist is None or dist > max_miles):
                continue
        best = best or (c["offices"][0] if c["offices"] else {})
        scored.append({
            "id": c["sra_number"], "name": c["name"], "work_areas": c["work_areas"],
            "matched_areas": [a for a in [primary, *secondary] if a in c["work_areas"]],
            "distance_miles": round(dist, 1) if dist is not None else None,
            "town": best.get("town"), "office": best, "office_count": len(c["offices"]),
            "register_url": c["register_url"], "sra_needs_check": c.get("sra_needs_check", False),
            "score": _score(c, primary, secondary, dist, max_miles),
        })
    scored.sort(key=lambda x: -x["score"])
    shortlist = scored[:25]  # keep the LLM prompt small + cheap

    if not shortlist:
        return _no_match(t, f"No firm covering {primary} within {max_miles:g} miles. "
                            "Try a bigger radius or allow remote/phone.")
    picks = ai.rerank(t, shortlist, top_n)
    by_id = {s["id"]: s for s in shortlist}
    firms = []
    for p in picks:
        f = by_id[p["id"]]
        firms.append({
            "sra_number": f["id"], "name": f["name"], "why": p["why"], "fit": p["fit"],
            "matched_areas": f["matched_areas"], "all_areas": f["work_areas"],
            "distance_miles": f["distance_miles"],
            "office": {k: f["office"].get(k) for k in ("address", "town", "postcode", "phone", "email", "website")},
            "verify_on_sra": f["register_url"], "sra_number_needs_check": f["sra_needs_check"],
            # Not in SRA data - filled by firm-supplied profiles later (see README)
            "free_initial_call": None, "legal_aid": None,
        })

    return {
        "triage": t,
        "firms": firms,
        "meta": {"data_source": _SOURCE, "candidates_considered": len(scored),
                 "searched_areas": [primary, *secondary],
                 "disclaimer": DISCLAIMER},
    }


DISCLAIMER = ("Firms are matched on the practice areas they list. This is not a recommendation of "
              "quality. Always check a firm on the SRA register before instructing it.")


def _no_match(t: dict, reason: str) -> dict:
    return {"triage": t, "firms": [],
            "meta": {"data_source": _SOURCE, "candidates_considered": 0, "no_match_reason": reason,
                     "fallback_links": FALLBACK_LINKS, "disclaimer": DISCLAIMER}}
