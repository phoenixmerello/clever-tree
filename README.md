# Legal Help API: self-help check + firm finder

Two features:
1. **`/api/assess`** decides whether the user can sort the problem themselves using official GOV.UK guidance, needs to answer a few questions first, or should see a solicitor.
2. **`/api/recommend-firms`** picks the best-matched firms from our directory, each with a reason.

**React flow:** call `/api/assess` first.
- `self_help` → show the guidance, plus a "Still stuck?" button that calls `/api/recommend-firms`.
- `ask_more` → show the questions and call `/api/assess` again.
- `specialist` → show the firms. They're already included in the response.

---

# Self-help vs specialist (`/api/assess`)

Our solicitor's rule: **if the answer can be found on GOV.UK (backed by legislation.gov.uk), it's self-help.**
The decision is made like this:

| Step | What happens |
|---|---|
| 1. Red flags | A red flag sends the user **straight to a specialist**, whatever else is true. There are 11 "always see a lawyer" rules in `firm_finder/red_flags.py` (court papers, criminal, safety, losing home, immigration, statutory demand, over £10k, other side has a lawyer, etc.). They're checked by regex **and** by the AI, so reworded versions are caught too. |
| 2. Retrieve | **Known topics first.** `firm_finder/topics.py` maps common problems to the right GOV.UK guides and legislation. Examples: unfair dismissal goes to `/dismissal` and `/employment-tribunals` plus the Employment Rights Act 1996 ss.94, 98 and 111; council debt goes to `/council-tax-arrears` plus the Local Government Finance Act 1992 and the Council Tax Regulations 1992. Topics are matched by keywords **and** by the AI. The AI also suggests extra legislation and writes GOV.UK-style search queries for anything not on the map. All of it is fetched from the official GOV.UK and legislation.gov.uk APIs. |
| 2b. Read the law | The text of the relevant legislation sections is fetched from legislation.gov.uk and given to the AI with the guidance. The AI says which sections actually apply, and only those are shown as "the law behind this". |
| 3. Ground | The AI picks the best section and must **copy the exact sentence** that answers the problem. The code checks that sentence is really on the page. If it isn't, there's no self-help answer. |
| 4. Score | Confidence is **calculated, not guessed**: 50 points if the quote is verified on GOV.UK, 20 if the page fully covers their situation (10 if partly), and 30 × the share of key facts we know. It's capped at 79 if a critical fact is missing or the coverage is only partial. |
| 5. Route | **80 or more → self-help.** Below 80 → up to 2 rounds of questions. Still below, or the user presses "I don't know" → specialist. If the GOV.UK page itself says "get legal advice" → specialist. |
| 6. Law | Every Act and section is **checked against legislation.gov.uk** before it's shown. A made-up Act or section never appears. |

If GOV.UK or the AI is down, it fails safe: the user is asked a question or sent to a specialist, never shown an unchecked answer.

### `POST /api/assess`
```json
{
  "problem": "My landlord won't return my £900 deposit",
  "user_type": "individual",
  "category": null,
  "answers": [],            // [{question, answer}] collected from earlier ask_more rounds
  "round": 0,               // how many question rounds the user has answered so far
  "unsure": false,          // true when user presses "I don't have more information"
  "postcode": "LS1 4DL", "max_miles": 25, "remote_ok": false,
  "find_firms": true        // include firm results when the route is specialist
}
```
Response (always the same shape):
```json
{
  "route": "self_help" | "ask_more" | "specialist",
  "confidence": 0-100,
  "confidence_breakdown": { "quote_verified": true, "coverage": "full", "facts_known": 2, "facts_total": 2,
                            "critical_missing": [], "capped_because": null, "...": "..." },
  "reason": "plain-English sentence to show the user",
  "red_flags": [{ "id": "losing_home", "label": "...", "why": "..." }],
  "emergency": null,         // e.g. "If you or anyone else is in immediate danger, call 999..." - show prominently
  "deadline_warning": "",
  "guidance": {              // present whenever a GOV.UK answer was verified (even on ask_more/specialist)
    "answer": "1. ... 2. ...",
    "quote": "exact sentence from GOV.UK",
    "source": { "title": "Tenancy deposit protection", "section": "Disputes and problems", "url": "https://www.gov.uk/..." },
    "law": [{ "title": "Housing Act 2004", "url": "https://www.legislation.gov.uk/ukpga/2004/34",
              "section": "213", "section_url": "https://www.legislation.gov.uk/ukpga/2004/34/section/213" }],
    "other_pages": [{ "title": "...", "url": "..." }]
  },
  "questions": ["..."],      // only for ask_more
  "round": 0, "max_rounds": 2,
  "triage": { "...": "..." },
  "next": { "action": "find_firms" | "offer_firms_if_stuck", "endpoint": "/api/recommend-firms", "triage": {} },
  "firms": { "...": "same shape as /api/recommend-firms" },   // only for specialist when find_firms=true
  "disclaimer": "..."
}
```
**Questions loop in React:** when `route` is `ask_more`, add each `{question, answer}` to `answers`, increase `round` by 1, and POST again. Send the same `problem` every time.

### Adding topics
Add a `Topic` to `firm_finder/topics.py`. Give it keywords, the GOV.UK paths and the `Law(title, year, sections)` entries. Check each GOV.UK path by opening `https://www.gov.uk/api/content/<path>`.

### Editing the red flags
`firm_finder/red_flags.py` has one `Rule` per red flag: a label, a plain-English reason, and regex patterns. Add or change patterns there, then run the tests.

### Tests
`python -m pytest -q` runs 35 offline tests, covering every route plus attempts to fake a quote, a page section or an Act. They include 48 checks that red flags fire when they should and stay quiet on everyday cases like parking fines, deposits and probate.

---

# Firm Finder

The "find me a solicitor" feature. A user describes their legal problem, and the feature returns the best-matched firms from our directory, each with a plain-English reason why it fits.

The AI only ranks firms that are actually in the data. It cannot invent a firm.

## Run it
```bash
pip install -r requirements.txt
cp .env.example .env          # put the Claude API key in ANTHROPIC_API_KEY
uvicorn app:app --reload --port 8000
```
Open http://localhost:8000 for a test page.
Without an API key it still runs, using keyword matching (good enough to check the plumbing).

## How it works
1. **Triage** (Claude Haiku). The problem is mapped onto the practice areas **that exist in our firm data**, so we never match to an area no firm covers. If nothing fits (e.g. a parking fine), it returns `NONE` rather than forcing a bad match.
2. **Filter** (plain code). The code keeps firms covering that area, finds each firm's nearest office (from the postcode via postcodes.io), and applies the radius.
3. **Rerank** (Claude Sonnet). The top 25 are ranked and each gets a "why this firm" line. Any firm ID that isn't in the list is thrown away.
4. **No match.** If no firm fits, the response has `firms: []`, a reason, and fallback links (Law Society Find a Solicitor, SRA register, legal aid checker).

## Data
`data/firms.xlsx` is the team's sample. It has one row per office, and rows with the same SRA number are merged into one firm.
Columns used: Name, Address, City, Phone number, Practice area (separated by `;`), SRA number.
- The postcode is pulled out of the Address.
- An SRA number with a note in the cell (e.g. "(verify – see Notes)") is flagged as `sra_number_needs_check: true`.
- Practice areas are used exactly as written. New areas added to the sheet are picked up automatically after a restart.

## API (for the React app)
All endpoints allow CORS from any origin.

### `POST /api/recommend-firms`
```json
{
  "problem": "A client owes my company £6k on an invoice 4 months overdue",
  "user_type": "business",          // "individual" | "business"
  "category": "Debt",               // optional: the category they clicked
  "postcode": "LS1 4DL",            // optional: enables distance
  "max_miles": 25,                  // optional
  "remote_ok": false,               // optional: true = ignore distance limit
  "top_n": 5,                       // optional, 1-10
  "triage": null                    // optional: pass a previous /api/triage result to skip that AI call
}
```
Response:
```json
{
  "triage": { "summary": "...", "problem_type": "...", "primary_area": "Bankruptcy/debt",
              "secondary_areas": [], "needs_solicitor": true, "urgency": "normal",
              "deadline_warning": "", "firm_traits": [] },
  "firms": [{
      "sra_number": "384855", "name": "Freeths LLP",
      "why": "Regional firm with a debt recovery team close to you",
      "fit": 88, "matched_areas": ["Bankruptcy/debt"], "all_areas": ["..."],
      "distance_miles": 0.4,
      "office": { "address": "...", "town": "Leeds", "postcode": "LS1 4DL", "phone": "...", "email": "", "website": "" },
      "verify_on_sra": "https://www.sra.org.uk/consumers/register/organisation/?sraNumber=384855",
      "sra_number_needs_check": false,
      "free_initial_call": null, "legal_aid": null
  }],
  "meta": { "data_source": "spreadsheet", "candidates_considered": 7,
            "no_match_reason": "(only when firms is empty)", "fallback_links": [ ... ],
            "disclaimer": "..." }
}
```
`free_initial_call` and `legal_aid` are placeholders for the future filters. That data isn't in the sheet yet.

### `POST /api/triage`
Same body as above. It returns only the `triage` object.

### `GET /api/practice-areas`
Returns every practice area in the data. Useful for building category buttons.

## Files
```
app.py                 FastAPI endpoints + test page (demo.html)
firm_finder/guidance.py   self-help vs specialist pipeline + confidence score
firm_finder/red_flags.py  'always see a lawyer' rules
firm_finder/topics.py     known problems -> GOV.UK guides + legislation
firm_finder/govuk.py      GOV.UK Search + Content API
firm_finder/legislation.py  verify Acts/sections on legislation.gov.uk
tests/                 offline test suite
firm_finder/ai.py      the two Claude calls (+ no-key fallback)
firm_finder/service.py the pipeline
firm_finder/sra.py     loads data/firms.xlsx (or the official SRA API if SRA_API_KEY is set)
firm_finder/geo.py     postcode -> distance
data/firms.xlsx        team sample
demo_data/             fictional firms, used only if there's no spreadsheet
```
