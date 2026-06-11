"""
Lever public postings API crawler.
Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json
No auth required.
"""

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings/{slug}"


async def fetch_postings(slug: str, company_name: str) -> list[dict]:
    url = BASE_URL.format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params={"mode": "json"})
            if response.status_code == 404:
                logger.warning(f"Lever: no postings found for slug={slug}")
                return []
            response.raise_for_status()
            jobs = response.json()
    except httpx.HTTPError as e:
        logger.error(f"Lever fetch failed for {slug}: {e}")
        return []

    if not isinstance(jobs, list):
        return []

    return [_normalize(job, slug, company_name) for job in jobs]


def _normalize(job: dict, slug: str, company_name: str) -> dict:
    location = job.get("categories", {}).get("location", "")
    commitment = job.get("categories", {}).get("commitment", "")

    content_parts = []
    if job.get("description"):
        content_parts.append(job["description"])
    for section in job.get("lists", []):
        content_parts.append(section.get("text", ""))
        content_parts.append(" ".join(section.get("content", [])))
    if job.get("additional"):
        content_parts.append(job["additional"])

    content_text = " ".join(content_parts)

    return {
        "external_id": job.get("id", ""),
        "company_name": company_name,
        "company_slug": slug,
        "ats_type": "lever",
        "title": job.get("text", ""),
        "location": location,
        "apply_url": job.get("applyUrl", job.get("hostedUrl", "")),
        "content_text": content_text,
        "raw_json": job,
        "dedup_hash": _dedup_hash(company_name, job.get("text", ""), location),
    }


def _dedup_hash(company: str, title: str, location: str) -> str:
    key = f"{company.lower()}|{title.lower()}|{location.lower()}"
    return hashlib.sha256(key.encode()).hexdigest()
