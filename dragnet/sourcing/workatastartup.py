"""
YC Work at a Startup — public company+jobs listing from workatastartup.com.
The /companies endpoint returns all YC-backed companies with their open roles.
No auth required. Heavily weighted toward Series A/B startups — perfect target pool.
"""

import hashlib
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

COMPANIES_URL = "https://www.workatastartup.com/companies.json"

RELEVANT_ROLE_KEYWORDS = {
    "backend", "software", "engineer", "developer", "platform", "infrastructure",
    "python", "golang", "api", "ml", "machine learning", "ai", "llm", "sde",
    "full stack", "fullstack", "data engineer", "devops", "generative",
}

RELEVANT_LOCATIONS = {
    "remote", "india", "bangalore", "delhi", "mumbai", "hyderabad",
    "worldwide", "anywhere",
}


async def fetch_postings() -> list[dict]:
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        ) as client:
            resp = await client.get(COMPANIES_URL)
            resp.raise_for_status()
            companies = resp.json()
    except Exception as e:
        logger.error(f"WorkAtAStartup fetch failed: {e}")
        return []

    results = []
    seen: set[str] = set()

    for company in companies:
        jobs = company.get("jobs") or []
        company_name = company.get("name") or ""
        for job in jobs:
            title = (job.get("title") or "").lower()
            locations = [
                (loc.get("text") or "").lower()
                for loc in (job.get("locations") or [])
            ]
            location_str = ", ".join(loc for loc in locations if loc) or "Remote"

            # Filter: relevant role title
            if not any(kw in title for kw in RELEVANT_ROLE_KEYWORDS):
                continue

            # Filter: remote or India-accessible
            is_remote = job.get("remote") or any(
                loc in " ".join(locations) for loc in RELEVANT_LOCATIONS
            )
            if not is_remote and not any(
                loc in location_str for loc in RELEVANT_LOCATIONS
            ):
                continue

            normalized = _normalize(job, company_name, location_str)
            if normalized["dedup_hash"] not in seen:
                seen.add(normalized["dedup_hash"])
                results.append(normalized)

    logger.info(f"WorkAtAStartup: {len(results)} relevant postings")
    return results


def _normalize(job: dict, company_name: str, location_str: str) -> dict:
    job_id = str(job.get("id") or "")
    title = (job.get("title") or "").strip()
    url = job.get("url") or f"https://www.workatastartup.com/jobs/{job_id}"

    posted_at = None
    if job.get("created_at"):
        try:
            posted_at = datetime.fromisoformat(str(job["created_at"]).replace("Z", "+00:00"))
        except Exception:
            pass

    content_text = " ".join(filter(None, [
        title, company_name, location_str,
        job.get("description", "")[:400],
    ]))

    return {
        "external_id": job_id,
        "title": title,
        "company_name": company_name,
        "location": location_str,
        "apply_url": url,
        "content_text": content_text,
        "raw_json": {
            "id": job_id, "title": title, "company": company_name,
            "location": location_str, "url": url,
            "remote": job.get("remote"),
        },
        "dedup_hash": hashlib.sha256(f"workatastartup:{job_id}".encode()).hexdigest(),
        "posted_at": posted_at,
        "salary_min": None,
        "salary_max": None,
        "source": "workatastartup",
    }
