"""
Job category definitions and fast-path categorizer.
Categories map to resume variants the user reviews and maintains.
No LLM used here — pure keyword heuristics, fast enough for all 945 jobs.
"""

from __future__ import annotations

CATEGORIES: dict[str, dict] = {
    "india_backend": {
        "label": "India — Backend / SDE",
        "description": (
            "India-based backend, SDE, SWE, or platform engineering roles. "
            "Emphasis: Go/Python, PostgreSQL, API design, production systems, observability."
        ),
        "resume_focus": "backend",
        "target_market": "india",
    },
    "india_ai": {
        "label": "India — AI / ML Engineer",
        "description": (
            "India-based AI, ML, LLM, or data engineering roles. "
            "Emphasis: RAG pipelines, LLM orchestration, MCP tooling, vector databases, agents."
        ),
        "resume_focus": "ai",
        "target_market": "india",
    },
    "global_backend": {
        "label": "Global Remote — Backend / SDE",
        "description": (
            "Remote-first backend or SDE roles open globally / via EOR. "
            "Emphasis: async collaboration, distributed systems, Go/Python, PostgreSQL."
        ),
        "resume_focus": "backend",
        "target_market": "global",
    },
    "global_ai": {
        "label": "Global Remote — AI / ML Engineer",
        "description": (
            "Remote-first AI/ML/LLM engineering roles open globally. "
            "Emphasis: RAG, LLM orchestration, agent systems, MCP, evaluation pipelines."
        ),
        "resume_focus": "ai",
        "target_market": "global",
    },
}

_AI_TITLE_SIGNALS = {
    "ai", "ml", "machine learning", "nlp", "llm", "language model",
    "data scientist", "data science", "genai", "gen ai", "generative",
    "deep learning", "neural", "computer vision", "cv engineer",
    "rag", "vector", "embedding", "agent", "applied scientist",
    "research engineer", "research scientist",
}

_INDIA_LOCATION_SIGNALS = {
    "india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad",
    "chennai", "pune", "kolkata", "noida", "gurgaon", "gurugram",
    "kochi", "kozhikode", "trivandrum", "jaipur", "ahmedabad",
    "kerala", "karnataka", "maharashtra", "telangana", "tamil nadu",
}

_GLOBAL_LOCATION_SIGNALS = {
    "remote", "worldwide", "anywhere", "global", "distributed",
    "work from home", "wfh", "eor", "employee of record",
}


def categorize_job(job: dict) -> str:
    """
    Assign one of the four categories to a job dict.
    Uses title + location keywords only — no LLM.
    """
    title = (job.get("title") or "").lower()
    location = (job.get("location") or "").lower()
    content = (job.get("content_text") or "").lower()[:500]

    is_ai = any(sig in title for sig in _AI_TITLE_SIGNALS)
    if not is_ai:
        is_ai = any(sig in content for sig in _AI_TITLE_SIGNALS)

    loc_text = f"{location} {content}"
    is_india = any(sig in loc_text for sig in _INDIA_LOCATION_SIGNALS)
    is_global = any(sig in loc_text for sig in _GLOBAL_LOCATION_SIGNALS)

    if not is_india and not is_global:
        is_india = True

    if is_global and not is_india:
        return "global_ai" if is_ai else "global_backend"
    return "india_ai" if is_ai else "india_backend"
