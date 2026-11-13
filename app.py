"""HTTP API for the front end.  Run:  uvicorn app:app --reload --port 8000

POST /api/recommend-firms
{
  "problem": "My landlord won't return my £900 deposit",
  "user_type": "individual" | "business",
  "category": "Housing",            # optional: what they clicked in the UI
  "postcode": "LS6 2AB",            # optional
  "max_miles": 25, "remote_ok": false, "top_n": 5,
  "triage": {...}                   # optional: reuse triage from the guidance step
}
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

# tiny .env loader (no extra dependency)
_env = Path(__file__).with_name(".env")
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from firm_finder import service  # noqa: E402

app = FastAPI(title="Firm Finder")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Req(BaseModel):
    problem: str = Field(min_length=5, max_length=5000)
    user_type: str = "individual"
    category: str | None = None
    postcode: str | None = None
    max_miles: float = 25
    remote_ok: bool = False
    top_n: int = Field(5, ge=1, le=10)
    triage: dict | None = None


@app.post("/api/recommend-firms")
def recommend(r: Req):
    try:
        return service.recommend(r.problem, r.user_type, r.postcode, r.category,
                                 r.max_miles, r.remote_ok, r.top_n, r.triage)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/triage")
def triage(r: Req):
    """Teammates can call this alone for the 'self-help vs solicitor' decision."""
    return service.run_triage(r.problem, r.user_type, r.category)


@app.get("/api/practice-areas")
def areas():
    """The practice areas in the loaded data - the React app can use these for category buttons."""
    return {"areas": service.practice_areas()}


@app.get("/")
def demo_page():
    return FileResponse(Path(__file__).with_name("demo.html"))
