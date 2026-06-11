"""
Remotive public API — remote-first jobs, many India-eligible.
Endpoint: https://remotive.com/api/remote-jobs
Free, no auth, no rate limit documented.
"""

import hashlib
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://remotive.com/api/remote-jobs"

RELEVANT_CATEGORIES = {
    "software-dev", "devops-sysadmin", "data", "all-others",
}

RELEVANT_KEYWORDS = {
    "backend", "python", "golang", "go ", "api", "platform",
    "infrastructure", "ml", "machine learning", "ai ", "llm",
    "full stack", "fullstack", "sde", "software engineer",
}


async def fetch_postings() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(API_URL, params={"limit": 500})
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
    except Exception as e:
        logger.error(f"Remotive fetch failed: {e}")
        return []

    results = []
    for job in jobs:
        title = (job.get("title") or "").lower()
        category = (job.get("category") or "").lower().replace(" ", "-")
        if not any(kw in title for kw in RELEVANT_KEYWORDS):
            continue
        results.append(_normalize(job))

    logger.info(f"Remotive: {len(results)} relevant postings")
    return results


def _normalize(job: dict) -> dict:
    job_id = str(job.get("id", ""))
    title = job.get("title", "").strip()
    company = job.get("company_name", "").strip()
    location = job.get("candidate_required_location", "Worldwide")
    url = job.get("url", "")

    posted_at = None
    if job.get("publication_date"):
        try:
            posted_at = datetime.fromisoformat(job["publication_date"].replace("Z", "+00:00"))
        except Exception:
            pass

    salary_min = salary_max = None
    salary_str = job.get("salary", "") or ""
    # Remotive salaries are free-text, skip parsing for now

    content_text = " ".join(filter(None, [
        title, company, location,
        job.get("description", "")[:500],
        " ".join(job.get("tags", [])),
    ]))

    return {
        "external_id": job_id,
        "title": title,
        "company_name": company,
        "location": location,
        "apply_url": url,
        "content_text": content_text,
        "raw_json": {
            "id": job_id, "title": title, "company": company,
            "location": location, "url": url,
            "salary": job.get("salary", ""),
            "tags": job.get("tags", []),
        },
        "dedup_hash": hashlib.sha256(f"remotive:{job_id}".encode()).hexdigest(),
        "posted_at": posted_at,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "source": "remotive",
    }
