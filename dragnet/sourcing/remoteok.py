"""
RemoteOK public API — tag-based remote job search, no auth required.
Endpoint: https://remoteok.com/api?tag=<tag>
Returns JSON array. First element is a legal disclaimer dict, skip it.
"""

import asyncio
import hashlib
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://remoteok.com/api"
DELAY = 2.0  # RemoteOK is rate-limit sensitive

TAGS = [
    "backend",
    "python",
    "golang",
    "software-engineer",
    "api",
    "machine-learning",
    "llm",
    "ai",
    "devops",
    "fullstack",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}


async def fetch_postings() -> list[dict]:
    seen: set[str] = set()
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=20.0, headers=HEADERS) as client:
        for tag in TAGS:
            try:
                resp = await client.get(BASE_URL, params={"tag": tag})
                if resp.status_code == 429:
                    logger.warning("RemoteOK rate limited")
                    await asyncio.sleep(10)
                    continue
                resp.raise_for_status()
                raw = resp.json()
            except Exception as e:
                logger.error(f"RemoteOK fetch failed for tag={tag}: {e}")
                await asyncio.sleep(DELAY)
                continue

            jobs = [j for j in raw if isinstance(j, dict) and j.get("id")]
            for job in jobs:
                norm = _normalize(job)
                if norm["dedup_hash"] not in seen:
                    seen.add(norm["dedup_hash"])
                    results.append(norm)

            await asyncio.sleep(DELAY)

    logger.info(f"RemoteOK: {len(results)} unique postings across {len(TAGS)} tags")
    return results


def _normalize(job: dict) -> dict:
    job_id = str(job.get("id") or "")
    title = (job.get("position") or "").strip()
    company = (job.get("company") or "").strip()
    location = (job.get("location") or "Worldwide").strip()
    url = job.get("url") or f"https://remoteok.com/remote-jobs/{job_id}"
    tags = job.get("tags") or []

    posted_at = None
    if job.get("date"):
        try:
            posted_at = datetime.fromisoformat(str(job["date"]).replace("Z", "+00:00"))
        except Exception:
            pass

    salary_min = job.get("salary_min")
    salary_max = job.get("salary_max")

    content_text = " ".join(filter(None, [title, company, location, " ".join(tags)]))

    return {
        "external_id": job_id,
        "title": title,
        "company_name": company,
        "location": location,
        "apply_url": url,
        "content_text": content_text,
        "raw_json": {
            "id": job_id, "title": title, "company": company,
            "location": location, "url": url, "tags": tags,
        },
        "dedup_hash": hashlib.sha256(f"remoteok:{job_id}".encode()).hexdigest(),
        "posted_at": posted_at,
        "salary_min": int(salary_min) if salary_min else None,
        "salary_max": int(salary_max) if salary_max else None,
        "source": "remoteok",
    }
