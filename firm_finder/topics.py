"""Known legal topics -> the right GOV.UK guidance and the legislation behind it.

Why: searching GOV.UK with the user's own words is unreliable ("my employer fired me unfairly"
returned 'Prove your right to work'). For common problems we know exactly where the official
guidance and law are. The AI also picks topics + proposes legislation, so wording that our
keywords miss is still caught; anything not covered here falls back to AI-written search queries.

Every GOV.UK path below was checked against the live GOV.UK Content API (13 Nov 2026).
Legislation is still verified at runtime on legislation.gov.uk before anything is shown.
Our solicitor can add/edit topics here - no other code changes needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Law:
    title: str          # short title as on legislation.gov.uk (no year)
    year: int
    sections: tuple = ()  # section numbers worth reading (Acts only)


@dataclass(frozen=True)
class Topic:
    id: str
    label: str
    keywords: list[str]
    govuk_paths: list[str]
    laws: list[Law] = field(default_factory=list)


TOPICS: list[Topic] = [
    Topic("unfair_dismissal", "Unfair dismissal",
          [r"\b(fired|sacked|dismiss\w*|let go|terminated|lost my job)\b"],
          ["/dismissal", "/employment-tribunals"],
          [Law("Employment Rights Act", 1996, ("94", "98", "111"))]),
    Topic("discrimination_at_work", "Discrimination at work",
          [r"\bdiscriminat\w*\b", r"\bbecause (i'?m|i am|of my) (pregnan\w*|disabled|disability|black|gay|trans|muslim|age|race|religion|gender|sex)\b",
           r"\b(pregnan\w*|maternity|disab\w*|racis\w*|sexis\w*|harass\w*)\b"],
          ["/discrimination-your-rights", "/employment-tribunals"],
          [Law("Equality Act", 2010, ("13", "26", "39"))]),
    Topic("redundancy", "Redundancy",
          [r"\bredundan\w*\b"],
          ["/redundancy-your-rights"],
          [Law("Employment Rights Act", 1996, ("135", "139"))]),
    Topic("council_tax_debt", "Council Tax arrears",
          [r"\bcouncil tax\b", r"\bcouncil\b.{0,40}\b(debt|arrears|owe|letter|summons|reminder|liability order)\b",
           r"\b(debt|arrears|owe\w*|letter|summons|reminder)\b.{0,40}\bcouncil\b", r"\bliability order\b"],
          ["/council-tax-arrears"],
          [Law("Local Government Finance Act", 1992),
           Law("Council Tax (Administration and Enforcement) Regulations", 1992)]),
    Topic("unpaid_invoice_business", "Late payment of a business invoice",
          [r"\b(invoice|client|customer)\b.{0,60}\b(unpaid|not paid|hasn'?t paid|won'?t pay|owe\w*|late|overdue)\b",
           r"\b(unpaid|overdue|late) (invoice|payment)s?\b"],
          ["/late-commercial-payments-interest-debt-recovery", "/make-court-claim-for-money"],
          [Law("Late Payment of Commercial Debts (Interest) Act", 1998)]),
    Topic("money_claim", "Claiming money you're owed",
          [r"\b(owes? me|owed|won'?t pay me back|get my money back|small claim\w*)\b"],
          ["/make-court-claim-for-money"]),
    Topic("tenancy_deposit", "Tenancy deposit dispute",
          [r"\bdeposit\b.{0,60}\b(landlord|tenan\w*|letting|agent|flat|house|rent\w*)\b",
           r"\b(landlord|letting agent)\b.{0,60}\bdeposit\b"],
          ["/tenancy-deposit-protection"],
          [Law("Housing Act", 2004, ("213", "214"))]),
    Topic("parking_ticket", "Parking ticket",
          [r"\bparking (ticket|fine|charge|notice)\b", r"\bpcn\b", r"\bpenalty charge notice\b"],
          ["/parking-tickets"],
          [Law("Traffic Management Act", 2004)]),
    Topic("faulty_goods", "Faulty goods or poor service",
          [r"\b(faulty|broken|not as described|refund|defective|stopped working|poor service|shoddy)\b"],
          ["/consumer-protection-rights"],
          [Law("Consumer Rights Act", 2015, ("9", "20", "49"))]),
    Topic("tax_dispute", "Disagreeing with HMRC",
          [r"\bhmrc\b", r"\btax (bill|penalty|decision|investigation)\b"],
          ["/tax-appeals"]),
]

TOPIC_IDS = [t.id for t in TOPICS]
BY_ID = {t.id: t for t in TOPICS}
_COMPILED = [(t, [re.compile(k, re.I) for k in t.keywords]) for t in TOPICS]


def match(text: str) -> list[str]:
    return [t.id for t, pats in _COMPILED if any(p.search(text) for p in pats)]


def describe_for_llm() -> str:
    return "\n".join(f"- {t.id}: {t.label}" for t in TOPICS)
