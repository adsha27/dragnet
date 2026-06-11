"""
Greenhouse public board API crawler.
Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
No auth required. Returns structured JSON with full job content.
"""

import hashlib
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


async def fetch_postings(slug: str, company_name: str) -> list[dict]:
    """Fetch all postings for a company slug. Returns normalized posting dicts."""
    url = BASE_URL.format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params={"content": "true"})
            if response.status_code == 404:
                logger.warning(f"Greenhouse: no board found for slug={slug}")
                return []
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error(f"Greenhouse fetch failed for {slug}: {e}")
        return []

    jobs = data.get("jobs", [])
    return [_normalize(job, slug, company_name) for job in jobs]


def _normalize(job: dict, slug: str, company_name: str) -> dict:
    content_text = ""
    if "content" in job:
        content_text = job["content"]

    location = ""
    if job.get("location"):
        location = job["location"].get("name", "")

    apply_url = job.get("absolute_url", f"https://boards.greenhouse.io/{slug}/jobs/{job['id']}")

    return {
        "external_id": str(job["id"]),
        "company_name": company_name,
        "company_slug": slug,
        "ats_type": "greenhouse",
        "title": job.get("title", ""),
        "location": location,
        "apply_url": apply_url,
        "content_text": content_text,
        "raw_json": job,
        "dedup_hash": _dedup_hash(company_name, job.get("title", ""), location),
    }


def _dedup_hash(company: str, title: str, location: str) -> str:
    key = f"{company.lower()}|{title.lower()}|{location.lower()}"
    return hashlib.sha256(key.encode()).hexdigest()
