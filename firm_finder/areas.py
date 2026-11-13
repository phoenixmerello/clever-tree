"""Official SRA 'work area' values (areas of law firms report to the SRA).
Source: https://www.sra.org.uk/datasharing  — the LLM must pick ONLY from this list,
so its output always lines up with the register data."""

SRA_WORK_AREAS = [
    "Arbitration and alternative dispute resolution",
    "Children",
    "Commercial/corporate work for listed companies",
    "Commercial/corporate work for non-listed companies",
    "Consumer",
    "Criminal",
    "Discrimination/civil liberties/human rights",
    "Employment",
    "Family/matrimonial",
    "Financial advice and services (Regulated by the SRA)",
    "Immigration",
    "Intellectual property",
    "Landlord and tenant (Commercial and Domestic)",
    "Litigation - other",
    "Mental health",
    "Non-litigation (other)",
    "Personal injury",
    "Planning",
    "Probate and estate administration",
    "Property commercial",
    "Property - residential",
    "Social welfare",
    "Wills, trusts and tax planning",
    "Claims management",
    "Payment protection insurance",
    "Youth Court",
]

_LOOKUP = {a.lower(): a for a in SRA_WORK_AREAS}


def canonical(area: str) -> str | None:
    """Map a free-text area back to the exact SRA label (case/spacing tolerant)."""
    if not area:
        return None
    key = " ".join(area.lower().split())
    return _LOOKUP.get(key)
