"""'Always see a lawyer' rules.

If ANY red flag fires, the user goes straight to the specialist route - no self-help,
whatever the confidence score. Two layers:
  1. Regex rules below (deterministic; can't be talked out of it; easy for our solicitor to edit).
  2. The triage LLM picks from the same rule ids, to catch paraphrases the regex misses.
False positives send someone to a solicitor (safe). False negatives are the dangerous direction,
so patterns lean broad, but each one is tested against everyday self-help cases
(parking fines, deposits, faulty goods, probate) to keep noise down.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    id: str
    label: str            # shown to the user
    why: str              # one line: why this needs a professional
    patterns: list[str] = field(default_factory=list)


_NEAR = r"[^.!?\n]{0,60}"   # same sentence, within ~60 chars
_SOON = (r"(today|tonight|tomorrow|this week|next week|this (monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
         r"|on (monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
         r"|(in|within) ([1-7]|one|two|three|four|five|six|seven|a couple of|a few) days?)")

RULES: list[Rule] = [
    Rule("court_proceedings", "Court or tribunal proceedings have started",
         "Once proceedings have started there are strict procedural rules and deadlines.",
         [r"\bcourt papers\b", r"\bclaim form\b", r"\bparticulars of claim\b", r"\bbeen served\b",
          r"\bserved (me )?with\b", r"\b(court|tribunal) hearing\b", r"\bhearing (date|is|on|next)\b",
          r"\bcourt order\b", r"\binjunction\b", r"\bsummons\b", r"\btaking me to court\b",
          r"\b(suing|sued) me\b", r"\bcounty court judg(e)?ment\b", r"\bccj\b"]),
    Rule("imminent_deadline", "A legal deadline is days away",
         "With only days left, a professional can act faster and protect your position.",
         [rf"\b(hearing|court|deadline|tribunal|appeal|respond|reply|evict\w*|bailiff\w*){_NEAR}\b{_SOON}\b",
          rf"\b{_SOON}\b{_NEAR}\b(hearing|court|deadline|tribunal|evict\w*|bailiff\w*)"]),
    Rule("criminal", "Police or criminal matter",
         "Anyone arrested or accused of a crime should get a criminal defence solicitor; "
         "free advice at the police station is a legal right.",
         [r"\barrested\b", r"\bcharged with\b", r"\b(police|voluntary) interview\b", r"\binterview under caution\b",
          r"\bunder caution\b", r"\bon (police )?bail\b", r"\breleased under investigation\b",
          r"\bmagistrates'? court\b", r"\bcrown court\b", r"\bcriminal record\b"]),
    Rule("safety_risk", "Someone's safety is at risk",
         "Safety comes first. Protective orders and urgent help need a professional.",
         [r"\bdomestic (abuse|violence)\b", r"\b(hit|hits|hitting|beat|beats|beating|hurt|hurts|hurting|threaten\w*) me\b",
          r"\b(afraid|scared) (of|for) (my|our) (life|lives|safety)\b", r"\bnot safe\b", r"\bcoercive control\b",
          r"\bstalk(ing|ed|er)\b", r"\bchild(ren)? (is|are|at) (at )?risk\b",
          r"\bsocial services\b.{0,40}\b(take|taking|remove|removing|took)\b", r"\bforced marriage\b"]),
    Rule("losing_home", "Losing your home is imminent",
         "When eviction or repossession is being enforced, specialist help can still stop or delay it.",
         [r"\bbailiffs?\b", r"\beviction (date|notice period ends)\b", r"\bpossession order\b",
          r"\bwarrant (of|for) possession\b", r"\blocked (me )?out\b", r"\billegal(ly)? evict\w*\b",
          r"\b(made|become|becoming|be) homeless\b", r"\brepossess\w*\b", r"\bchanged the locks\b"]),
    Rule("immigration_status", "Immigration status at risk",
         "Immigration advice is regulated and mistakes can affect your right to stay.",
         [r"\bdeport\w*\b", r"\bremoval (notice|directions)\b", r"\bdetention (centre|center)\b", r"\bdetained\b",
          r"\b(visa|leave to remain|asylum)\b.{0,40}\b(refused|rejected|revoked|curtailed|expired|cancelled)\b",
          r"\boverstay\w*\b"]),
    Rule("other_side_has_lawyer", "The other side is using a solicitor",
         "If they have legal representation you're at a disadvantage without it.",
         [r"\b(their|his|her|a|the landlord'?s|my employer'?s) (solicitor|lawyer)s?\b.{0,40}\b(letter|wrote|sent|email|contacted|acting)\b",
          r"\bletter (from|by) (their|his|her|a|the) (solicitor|lawyer)s?\b",
          r"\bletter before (action|claim)\b", r"\bsolicitors? acting for\b"]),
    Rule("business_insolvency", "Insolvency or a statutory demand",
         "Statutory demands and winding-up or bankruptcy petitions have very short, strict time limits.",
         [r"\bstatutory demand\b", r"\bwinding[- ]up (petition|order)\b", r"\bbankruptcy petition\b",
          r"\binsolven\w*\b", r"\bgo(ing)? into (administration|liquidation)\b", r"\bliquidat\w*\b"]),
    Rule("serious_harm", "Serious injury or medical negligence",
         "These claims need expert evidence and have strict time limits.",
         [r"\b(medical|clinical) negligence\b", r"\bmisdiagnos\w*\b", r"\b(surgery|operation) went wrong\b",
          r"\bserious(ly)? injur\w*\b", r"\blife[- ]changing injur\w*\b", r"\bbrain injur\w*\b"]),
    Rule("capacity", "Mental capacity or Court of Protection",
         "Decisions for someone who lacks capacity are tightly regulated.",
         [r"\black(s|ing)? (mental )?capacity\b", r"\bcourt of protection\b", r"\bsectioned\b",
          r"\bdeprivation of liberty\b"]),
    Rule("high_value", "Over £10,000 at stake",
         "Claims over £10,000 fall outside the small claims track, where costs and procedure get serious.",
         []),  # handled by _amounts() below
]

RULE_IDS = [r.id for r in RULES]
_BY_ID = {r.id: r for r in RULES}
_COMPILED = [(r, [re.compile(p, re.I) for p in r.patterns]) for r in RULES]

SMALL_CLAIMS_LIMIT = 10_000  # England & Wales small claims track limit (GBP)
_MONEY = re.compile(
    r"(?:£\s?(?P<a>\d[\d,]*(?:\.\d+)?)\s?(?P<as>k|m|thousand|million|grand)?)"
    r"|(?:\b(?P<b>\d[\d,]*(?:\.\d+)?)\s?(?P<bs>k|m|thousand|million|grand)?\s?(?:pounds|quid|gbp)\b)",
    re.I)
_MULT = {"k": 1e3, "thousand": 1e3, "grand": 1e3, "m": 1e6, "million": 1e6}


def _amounts(text: str) -> list[float]:
    out = []
    for m in _MONEY.finditer(text):
        num, suf = (m.group("a"), m.group("as")) if m.group("a") else (m.group("b"), m.group("bs"))
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        out.append(v * _MULT.get((suf or "").lower(), 1))
    return out


def detect(text: str) -> list[dict]:
    """Regex layer. Returns [{id,label,why,matched}]."""
    hits = []
    for rule, pats in _COMPILED:
        for p in pats:
            m = p.search(text)
            if m:
                hits.append({"id": rule.id, "label": rule.label, "why": rule.why, "matched": m.group(0)})
                break
    big = [a for a in _amounts(text) if a > SMALL_CLAIMS_LIMIT]
    if big:
        r = _BY_ID["high_value"]
        hits.append({"id": r.id, "label": r.label, "why": r.why, "matched": f"£{max(big):,.0f}"})
    return hits


def from_ids(ids: list[str], source: str = "ai") -> list[dict]:
    return [{"id": i, "label": _BY_ID[i].label, "why": _BY_ID[i].why, "matched": source}
            for i in ids if i in _BY_ID]


def merge(*lists: list[dict]) -> list[dict]:
    seen, out = set(), []
    for lst in lists:
        for f in lst:
            if f["id"] not in seen:
                seen.add(f["id"])
                out.append(f)
    return out


def describe_for_llm() -> str:
    return "\n".join(f"- {r.id}: {r.label}. {r.why}" for r in RULES)


EMERGENCY_IDS = {"safety_risk"}
EMERGENCY_MESSAGE = ("If you or anyone else is in immediate danger, call 999. "
                     "Legal aid is often available for victims of domestic abuse: "
                     "https://www.gov.uk/legal-aid/domestic-abuse")
