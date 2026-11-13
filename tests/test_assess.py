"""Offline tests for /api/assess. HTTP and LLM are faked with fixtures shaped like the real APIs
(GOV.UK search + content API, legislation.gov.uk Atom feed). Run:  python -m pytest -q"""
import types

import pytest
from fastapi.testclient import TestClient

import app as app_module
from firm_finder import ai, govuk, guidance, legislation, red_flags, service

# ---------------------------------------------------------------- fixtures (shape = real APIs)
DEPOSIT_OVERVIEW = ("<p>Your landlord must put your deposit in a government-approved tenancy deposit scheme "
                    "(TDP) if you rent your home on an assured shorthold tenancy that started after 6 April 2007.</p>")
DEPOSIT_DISPUTES = ("<h2>If you and your landlord disagree</h2><p>Contact the tenancy deposit protection scheme "
                    "your landlord used if you can&#8217;t agree on how much of the deposit will be returned.</p>"
                    "<p>The scheme&#8217;s free dispute resolution service will decide how much is returned.</p>"
                    "<ul><li>You do not have to use the service.</li></ul>"
                    "<p>Read the <a href=\"https://www.legislation.gov.uk/ukpga/2004/34/section/213\">law</a>.</p>")
SEARCH = {"results": [
    {"title": "Tenancy deposit protection", "link": "/tenancy-deposit-protection", "format": "guide",
     "content_store_document_type": "guide", "description": "A tenant's guide"},
    {"title": "Housing minister speech", "link": "/government/speeches/x", "format": "speech",
     "content_store_document_type": "speech", "description": ""},
    {"title": "Private renting", "link": "/private-renting", "format": "guide",
     "content_store_document_type": "guide", "description": ""},
]}
CONTENT = {
    "/tenancy-deposit-protection": {"base_path": "/tenancy-deposit-protection", "title": "Tenancy deposit protection",
                                    "document_type": "guide", "details": {"parts": [
                                        {"slug": "overview", "title": "Overview", "body": DEPOSIT_OVERVIEW},
                                        {"slug": "disputes-and-problems", "title": "Disputes and problems",
                                         "body": DEPOSIT_DISPUTES}]}},
    "/private-renting": {"base_path": "/private-renting", "title": "Private renting", "document_type": "guide",
                         "details": {"parts": [{"slug": "your-rights", "title": "Your rights",
                                                "body": "<p>You have the right to live in a property that's safe.</p>"}]}},
}
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://www.legislation.gov.uk/id/ukpga/2004/34</id><title>Housing Act 2004</title></entry>
<entry><id>http://www.legislation.gov.uk/id/ukpga/1988/50</id><title>Housing Act 1988</title></entry></feed>"""

SECTION_XML = ("<Legislation xmlns='http://www.legislation.gov.uk/namespaces/legislation'><Primary><Body><P1group>"
               "<Title>Tenancy deposits: requirements</Title><P1><P1para><Text>Any tenancy deposit paid must be dealt "
               "with in accordance with an authorised scheme.</Text></P1para></P1></P1group></Body></Primary></Legislation>")
GOOD_QUOTE = ("The scheme’s free dispute resolution service will decide how much is returned.")  # curly ' on purpose


def triage_fx(**kw):
    t = {"summary": "Tenant's landlord is keeping the deposit", "problem_type": "tenancy deposit dispute",
         "primary_area": "Leasehold", "secondary_areas": [], "needs_solicitor": False, "urgency": "normal",
         "deadline_warning": "", "firm_traits": [], "search_queries": ["tenancy deposit dispute"],
         "red_flags": [], "topics": [], "legislation": [], "_engine": "test"}
    t.update(kw)
    return t


def ground_fx(**kw):
    g = {"best_section_id": "S2", "coverage": "full", "quote": GOOD_QUOTE,
         "answer": "1. Ask your landlord which scheme protects your deposit.\n2. Use its free dispute service.",
         "facts": [{"fact": "whether the deposit was protected", "critical": True, "known": True},
                   {"fact": "tenancy type", "critical": False, "known": True}],
         "page_says_get_advice": False, "law_ids_used": ["L1"]}
    g.update(kw)
    return g


@pytest.fixture
def env(monkeypatch):
    calls = {"govuk": [], "ground": 0, "firms": 0, "leg": []}

    def fake_get_json(url, params=None):
        calls["govuk"].append(url)
        if url.endswith("/api/search.json"):
            return SEARCH
        return CONTENT[url.split("/api/content", 1)[1]]

    def fake_leg_get(url, params=None):
        calls["leg"].append(url)
        if url.endswith("/ukpga/2004/data.feed"):
            return 200, ATOM
        if url.endswith("/data.feed"):
            return 200, '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        if url.endswith("/ukpga/2004/34/section/213/data.xml"):
            return 200, SECTION_XML
        return 404, ""

    state = {"triage": triage_fx(), "ground": ground_fx()}

    def fake_ground(*a, **k):
        calls["ground"] += 1
        return state["ground"]

    def fake_recommend(**k):
        calls["firms"] += 1
        return {"firms": [{"name": "Test Firm"}]}

    legislation.locate.cache_clear()
    monkeypatch.setattr(govuk, "_get_json", fake_get_json)
    monkeypatch.setattr(legislation, "_get", fake_leg_get)
    monkeypatch.setattr(service, "run_triage", lambda *a, **k: state["triage"])
    monkeypatch.setattr(guidance, "_call_tool", fake_ground)
    monkeypatch.setattr(service, "recommend", fake_recommend)
    return types.SimpleNamespace(calls=calls, state=state)


P = "My landlord won't give my £900 deposit back, says I damaged the carpet but it was already like that"


# ---------------------------------------------------------------- routes
def test_self_help_when_verified_full_and_facts_known(env):
    r = guidance.assess(P)
    assert r["route"] == "self_help", r["reason"]
    assert r["confidence"] == 100
    g = r["guidance"]
    assert g["source"]["url"] == "https://www.gov.uk/tenancy-deposit-protection/disputes-and-problems"
    assert g["source"]["section"] == "Disputes and problems"
    assert g["law"] == [{"title": "Housing Act 2004", "url": "https://www.legislation.gov.uk/ukpga/2004/34",
                         "section": "213", "section_url": "https://www.legislation.gov.uk/ukpga/2004/34/section/213",
                         "applies": True}]                                              # s.214 404'd -> not shown
    assert r["topics"] == [{"id": "tenancy_deposit", "label": "Tenancy deposit dispute"}]
    assert env.calls["firms"] == 0                                                      # no firm lookup needed
    assert not any("speeches" in u for u in env.calls["govuk"])                        # speech filtered out


def test_missing_critical_fact_asks_question_capped_79(env):
    env.state["ground"] = ground_fx(facts=[
        {"fact": "whether the deposit was protected", "critical": True, "known": False,
         "question": "Did your landlord tell you which deposit scheme they used?"},
        {"fact": "tenancy type", "critical": False, "known": True}])
    r = guidance.assess(P)
    assert r["route"] == "ask_more"
    assert r["confidence"] == 79 and r["confidence_breakdown"]["capped_because"] == "a key fact is missing"
    assert r["questions"] == ["Did your landlord tell you which deposit scheme they used?"]
    assert r["guidance"] is not None          # verified reading still available to show alongside


def test_partial_coverage_never_self_help(env):
    env.state["ground"] = ground_fx(coverage="partial")
    r = guidance.assess(P)
    assert r["route"] == "ask_more" and r["confidence"] == 79


def test_after_two_rounds_escalates(env):
    env.state["ground"] = ground_fx(facts=[{"fact": "x", "critical": True, "known": False, "question": "x?"}])
    assert guidance.assess(P, round_no=1)["route"] == "ask_more"
    r = guidance.assess(P, round_no=2)
    assert r["route"] == "specialist" and r["firms"] == {"firms": [{"name": "Test Firm"}]}
    assert r["next"]["action"] == "find_firms"


def test_unsure_goes_straight_to_specialist(env):
    r = guidance.assess(P, unsure=True)
    assert r["route"] == "specialist" and env.calls["ground"] == 0


def test_invented_quote_is_rejected(env):
    env.state["ground"] = ground_fx(quote="Your landlord must return your deposit within 10 days of the tenancy ending.")
    r = guidance.assess(P)
    assert r["confidence_breakdown"]["quote_verified"] is False
    assert r["confidence"] <= 30 and r["guidance"] is None and r["route"] == "ask_more"


def test_quote_with_ellipsis_rejected(env):
    env.state["ground"] = ground_fx(quote="The scheme's free dispute resolution ... is returned.")
    assert guidance.assess(P)["confidence_breakdown"]["quote_verified"] is False


def test_quote_from_wrong_section_rejected(env):
    env.state["ground"] = ground_fx(best_section_id="S1")   # quote is in S2, not S1
    assert guidance.assess(P)["guidance"] is None


def test_made_up_section_id(env):
    env.state["ground"] = ground_fx(best_section_id="S99")
    r = guidance.assess(P)
    assert r["guidance"] is None and r["route"] == "ask_more"


def test_regex_red_flag_skips_govuk(env):
    r = guidance.assess("The bailiffs are coming tomorrow to evict us")
    assert r["route"] == "specialist"
    assert {"losing_home", "imminent_deadline"} <= {f["id"] for f in r["red_flags"]}
    assert env.calls["govuk"] == [] and env.calls["ground"] == 0


def test_ai_red_flag_paraphrase(env):
    env.state["triage"] = triage_fx(red_flags=["court_proceedings"])
    r = guidance.assess("I got some official looking papers from the court about my old flat")
    assert r["route"] == "specialist" and r["red_flags"][0]["matched"] in ("ai", "court papers")


def test_red_flag_in_followup_answer(env):
    r = guidance.assess(P, answers=[{"question": "Anything else?", "answer": "Their solicitor sent me a letter"}],
                        round_no=1)
    assert r["route"] == "specialist" and r["red_flags"][0]["id"] == "other_side_has_lawyer"


def test_safety_shows_emergency(env):
    r = guidance.assess("My partner hits me and I want to move out with the kids")
    assert r["route"] == "specialist" and "999" in r["emergency"]


def test_page_says_get_advice(env):
    env.state["ground"] = ground_fx(page_says_get_advice=True)
    r = guidance.assess(P)
    assert r["route"] == "specialist" and r["guidance"] is not None


def test_govuk_down(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(govuk, "_get_json", boom)
    r = guidance.assess(P)
    assert r["route"] == "ask_more"
    assert guidance.assess(P, round_no=2)["route"] == "specialist"


def test_llm_unavailable_is_safe(env):
    env.state["ground"] = None
    r = guidance.assess(P)
    assert r["route"] == "specialist" and r["related_pages"]


def test_ai_suggested_fake_act_dropped(env):
    env.state["triage"] = triage_fx(legislation=[{"title": "Deposit Return Act", "year": 2019, "sections": ["4"]}])
    urls = [x["url"] for x in guidance.assess(P)["guidance"]["law"]]
    assert all("2019" not in u for u in urls)


def test_legislation_text_sent_to_ai(env, monkeypatch):
    seen = {}
    def grab(model, system, tool, user, **k):
        seen["user"] = user
        return ground_fx()
    monkeypatch.setattr(guidance, "_call_tool", grab)
    guidance.assess(P)
    assert '"id": "L1"' in seen["user"] and "authorised scheme" in seen["user"]
    assert '"title": "Housing Act 2004 s.213"' in seen["user"]


def test_quote_from_legislation_not_accepted_as_guidance(env):
    env.state["ground"] = ground_fx(best_section_id="L1",
                                    quote="Any tenancy deposit paid must be dealt with in accordance with an authorised scheme.")
    r = guidance.assess(P)
    assert r["guidance"] is None and r["route"] != "self_help"


def test_known_topic_page_fetched_even_if_search_misses(env, monkeypatch):
    real = govuk._get_json
    monkeypatch.setattr(govuk, "_get_json", lambda url, params=None: {"results": []} if url.endswith("search.json") else real(url, params))
    r = guidance.assess(P)
    assert r["route"] == "self_help" and "tenancy-deposit-protection" in r["guidance"]["source"]["url"]


# ---------------------------------------------------------------- units
def test_score_table():
    s = guidance.score
    assert s(True, "full", [])["confidence"] == 100
    assert s(True, "full", [{"fact": "a", "known": True}, {"fact": "b", "known": False}])["confidence"] == 85
    assert s(False, "full", [])["confidence"] == 30
    assert s(True, "none", [])["confidence"] == 79
    assert s(True, "partial", [])["breakdown"]["capped_because"].startswith("the guidance only partly")


def test_html_to_text():
    text, links = govuk.html_to_text(DEPOSIT_DISPUTES)
    assert "can’t agree" in text and "- You do not have to use the service." in text
    assert links == ["https://www.legislation.gov.uk/ukpga/2004/34/section/213"]


def test_answer_schema_body_list():
    secs = govuk._details_html({"body": [{"content_type": "text/govspeak", "content": "x"},
                                         {"content_type": "text/html", "content": "<p>Hello there</p>"}]})
    assert secs and "Hello there" in secs[0][2]


def test_red_flags_list_matches_ai_enum():
    assert set(red_flags.RULE_IDS) == {r.id for r in red_flags.RULES}


# ---------------------------------------------------------------- real SDK call path, fake transport
def test_call_tool_uses_forced_tool(monkeypatch):
    seen = {}

    class Msgs:
        def create(self, **kw):
            seen.update(kw)
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="tool_use", input={"ok": 1})])
    monkeypatch.setattr(ai, "_client", lambda: types.SimpleNamespace(messages=Msgs()))
    assert guidance._call_tool("m", "sys", guidance.GROUND_TOOL, "hi") == {"ok": 1}
    assert seen["tool_choice"] == {"type": "tool", "name": "ground_answer"}


def test_classify_adds_queries_and_filters_flags(monkeypatch):
    class Msgs:
        def create(self, **kw):
            assert "red_flags" in kw["tools"][0]["input_schema"]["properties"]
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="tool_use", input={
                "summary": "s", "problem_type": "p", "primary_area": "Employment", "secondary_areas": ["Made up"],
                "needs_solicitor": True, "urgency": "normal", "search_queries": ["unfair dismissal", " "],
                "red_flags": ["court_proceedings", "not_a_flag"]})])
    monkeypatch.setattr(ai, "_client", lambda: types.SimpleNamespace(messages=Msgs()))
    t = ai.classify("I was sacked", ["Employment", "Planning"])
    assert t["red_flags"] == ["court_proceedings"] and t["search_queries"] == ["unfair dismissal"]
    assert t["secondary_areas"] == []


# ---------------------------------------------------------------- HTTP contract
def test_endpoint(env):
    c = TestClient(app_module.app)
    r = c.post("/api/assess", json={"problem": P, "postcode": "LS6 2AB"})
    assert r.status_code == 200 and r.json()["route"] == "self_help"
    r = c.post("/api/assess", json={"problem": P, "round": 1, "unsure": True,
                                    "answers": [{"question": "q?", "answer": "not sure"}]})
    assert r.json()["route"] == "specialist"
    assert c.post("/api/assess", json={"problem": "hi"}).status_code == 422


def test_legislation_year_listing_used_first(env):
    a = legislation.find_act("Housing Act", 2004, "213")
    assert a["url"] == "https://www.legislation.gov.uk/ukpga/2004/34"
    assert env.calls["leg"][0].endswith("/ukpga/2004/data.feed")
    assert a["section_url"] == "https://www.legislation.gov.uk/ukpga/2004/34/section/213"


def test_legislation_wrong_year_not_matched(env):
    assert legislation.find_act("Housing Act", 1999) is None


def test_legislation_title_with_year_inline(env):
    assert legislation.find_act("Housing Act 2004")["url"].endswith("/ukpga/2004/34")


def test_users_examples_hit_right_topics():
    from firm_finder.topics import match
    assert match("my employer fired me unfairly") == ["unfair_dismissal"]
    assert set(match("I was sacked because I'm pregnant")) == {"unfair_dismissal", "discrimination_at_work"}
    assert match("I've received a debt letter from the local council") == ["council_tax_debt"]
    assert "unpaid_invoice_business" in match("A client hasn't paid our invoice for 3 months")
    assert match("I got a parking fine") == ["parking_ticket"]
    assert match("My neighbour's tree is blocking my light") == []


def test_legislation_resolve_merges_and_falls_back(env):
    out = legislation.resolve([{"title": "Housing Act", "year": 2004, "sections": ["213"]},
                               {"title": "Housing Act 2004", "sections": ["213", "999"]},
                               {"title": "Made Up Act", "year": 2020}])
    assert [(o["title"], o["section"]) for o in out] == [("Housing Act 2004", "213")]


def test_legislation_act_without_sections_linked(env):
    out = legislation.resolve([{"title": "Housing Act", "year": 2004}])
    assert out[0]["url"].endswith("/ukpga/2004/34") and out[0]["section"] is None
