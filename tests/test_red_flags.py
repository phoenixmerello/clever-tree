from firm_finder.red_flags import detect

SHOULD_FIRE = {
 "court_proceedings": ["I have received a claim form from the county court", "They are taking me to court over the invoice", "I got a CCJ"],
 "imminent_deadline": ["My hearing is tomorrow and I have no idea what to do", "The deadline to respond is in 3 days", "bailiffs are coming on Monday"],
 "criminal": ["I was arrested last night", "My son has been charged with assault", "I have a police interview next week"],
 "safety_risk": ["My partner hits me and I want to leave", "I am scared for my safety", "social services are trying to take my kids"],
 "losing_home": ["The bailiffs are coming", "My landlord changed the locks while I was out", "we have a possession order"],
 "immigration_status": ["My visa was refused and I might be deported", "My leave to remain has expired"],
 "other_side_has_lawyer": ["I got a letter from their solicitor demanding money", "I received a letter before action"],
 "business_insolvency": ["A supplier served a statutory demand on my company", "we might go into liquidation"],
 "serious_harm": ["I think there was medical negligence during my birth", "I was seriously injured at work"],
 "capacity": ["my mum lacks capacity and my brother is taking her money"],
 "high_value": ["They owe me \u00a315,000", "a claim worth 25k pounds", "\u00a31.2m contract dispute", "\u00a312k unpaid invoice"],
}
SHOULD_NOT_FIRE = [
 "My landlord won't return my \u00a3900 deposit", "I got a parking fine and must pay within 14 days",
 "The shop charged me \u00a350 for a broken kettle", "My dad died and I need to apply for probate",
 "I want to appeal my council tax band", "My employer has not paid my holiday pay of \u00a3600",
 "I was charged twice for my gym membership", "I bought a faulty laptop for \u00a31,200",
 "A customer owes us \u00a36,000 on an invoice", "I reported the theft of my bike to the police",
 "My neighbour's tree is blocking my light", "I need a will", "I owe \u00a310,000 on a loan", "Someone copied my logo",
 "My flight was cancelled and the airline won't refund me", "I want to change my name by deed poll",
 "My boss sacked me after I told him I was pregnant", "My employer wants to cut my hours next month",
]


def test_fires():
    for rule, cases in SHOULD_FIRE.items():
        for c in cases:
            assert rule in [h["id"] for h in detect(c)], (rule, c)


def test_quiet_on_everyday_problems():
    for c in SHOULD_NOT_FIRE:
        assert detect(c) == [], (c, detect(c))
