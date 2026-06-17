"""
Ashby public job board API crawler.
Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}
No auth required. Returns JSON with job listings.
"""

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


async def fetch_postings(slug: str, company_name: str) -> list[dict]:
    url = BASE_URL.format(slug=slug)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 404:
                logger.warning(f"Ashby: no board found for slug={slug}")
                return []
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error(f"Ashby fetch failed for {slug}: {e}")
        return []

    jobs = data.get("jobPostings", [])
    return [_normalize(job, slug, company_name) for job in jobs]


def _normalize(job: dict, slug: str, company_name: str) -> dict:
    location = ""
    if job.get("locationName"):
        location = job["locationName"]
    elif job.get("isRemote"):
        location = "Remote"

    import html as html_mod, re
    raw = job.get("descriptionHtml", "") or job.get("descriptionPlain", "")
    raw = html_mod.unescape(raw)
    content_text = re.sub(r"\s{2,}", " ", re.sub(r"<[^>]+>", " ", raw)).strip()

    return {
        "external_id": job.get("id", ""),
        "company_name": company_name,
        "company_slug": slug,
        "ats_type": "ashby",
        "title": job.get("title", ""),
        "location": location,
        "apply_url": job.get("jobUrl", f"https://jobs.ashbyhq.com/{slug}/{job.get('id', '')}"),
        "content_text": content_text,
        "raw_json": job,
        "dedup_hash": _dedup_hash(company_name, job.get("title", ""), location),
    }


def _dedup_hash(company: str, title: str, location: str) -> str:
    key = f"{company.lower()}|{title.lower()}|{location.lower()}"
    return hashlib.sha256(key.encode()).hexdigest()
