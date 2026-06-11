"""
Himalayas.app public API — remote-first jobs, no auth required.
Endpoint: https://himalayas.app/jobs/api
Returns JSON array of remote jobs. Many are India-eligible (EOR/contractor).
"""

import hashlib
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://himalayas.app/jobs/api"

RELEVANT_KEYWORDS = {
    "backend", "software engineer", "software developer", "platform",
    "python", "golang", "go developer", "api engineer", "infrastructure",
    "ml engineer", "machine learning", "ai engineer", "llm", "fullstack",
    "full stack", "sde", "data engineer", "devops",
}


async def fetch_postings(pages: int = 10) -> list[dict]:
    """
    Paginate through Himalayas jobs (20 per page, no category filter available).
    Filter client-side by title keyword. 10 pages = 200 scanned, ~20-40 tech jobs.
    """
    all_jobs: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for page in range(pages):
                resp = await client.get(API_URL, params={"limit": 20, "offset": page * 20})
                resp.raise_for_status()
                data = resp.json()
                batch = data.get("jobs", [])
                if not batch:
                    break
                all_jobs.extend(batch)
    except Exception as e:
        logger.error(f"Himalayas fetch failed: {e}")
        return []

    jobs = all_jobs

    results = []
    for job in jobs:
        title = (job.get("title") or "").lower()
        if not any(kw in title for kw in RELEVANT_KEYWORDS):
            continue
        results.append(_normalize(job))

    logger.info(f"Himalayas: {len(results)} relevant postings from {len(jobs)} total")
    return results


def _normalize(job: dict) -> dict:
    job_id = str(job.get("guid") or job.get("id") or job.get("slug") or "")
    title = (job.get("title") or "").strip()
    company = (job.get("companyName") or job.get("company", {}).get("name") or "").strip()
    location = (job.get("locationRestrictions") or "Worldwide")
    if isinstance(location, list):
        location = ", ".join(location)
    url = job.get("applicationLink") or job.get("url") or f"https://himalayas.app/jobs/{job_id}"

    posted_at = None
    for date_field in ("publishedAt", "createdAt", "postedAt"):
        if job.get(date_field):
            try:
                posted_at = datetime.fromisoformat(str(job[date_field]).replace("Z", "+00:00"))
                break
            except Exception:
                pass

    salary_min = job.get("salaryMin") or job.get("minSalary")
    salary_max = job.get("salaryMax") or job.get("maxSalary")

    content_text = " ".join(filter(None, [
        title, company, str(location),
        " ".join(job.get("categories") or []),
        " ".join(job.get("tags") or []),
    ]))

    return {
        "external_id": job_id,
        "title": title,
        "company_name": company,
        "location": str(location),
        "apply_url": url,
        "content_text": content_text,
        "raw_json": {
            "id": job_id, "title": title, "company": company,
            "location": location, "url": url,
            "salary_min": salary_min, "salary_max": salary_max,
        },
        "dedup_hash": hashlib.sha256(f"himalayas:{job_id}".encode()).hexdigest(),
        "posted_at": posted_at,
        "salary_min": int(salary_min) if salary_min else None,
        "salary_max": int(salary_max) if salary_max else None,
        "source": "himalayas",
    }
