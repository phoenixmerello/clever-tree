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
app.py                 FastAPI endpoints + test page
firm_finder/ai.py      the two Claude calls (+ no-key fallback)
firm_finder/service.py the pipeline
firm_finder/sra.py     loads data/firms.xlsx (or the official SRA API if SRA_API_KEY is set)
firm_finder/geo.py     postcode -> distance
data/firms.xlsx        team sample
demo_data/             fictional firms, used only if there's no spreadsheet
```
