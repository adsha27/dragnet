"""
LinkedIn Jobs crawler.
Uses LinkedIn's guest job search endpoint — no auth required for basic search.
Endpoint: https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search

LinkedIn aggressively rate-limits bots. We add jitter between requests and
use a realistic UA. If this gets blocked, the Browserbase fallback applies
(set LINKEDIN_USE_BROWSER=1 in .env to route through Stagehand instead).

LinkedIn is critical for India-based hiring: most Indian startups post here
even when they don't have Greenhouse/Lever/Ashby boards.
"""

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

GUEST_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JOB_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
PAGE_SIZE = 10
MAX_PAGES = 10
DELAY_BETWEEN_REQUESTS = 1.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.linkedin.com/jobs/",
}

INDIA_QUERIES = [
    # Role × location matrix — covers the full relevant search space
    # Broad India sweep
    ("backend engineer", "India"),
    ("software engineer", "India"),
    ("software developer", "India"),
    ("backend developer", "India"),
    ("api engineer", "India"),
    ("platform engineer", "India"),
    ("sde", "India"),
    ("sde-2", "India"),
    ("sde 2", "India"),
    # Language-specific — high signal for your stack
    ("golang engineer", "India"),
    ("go developer", "India"),
    ("python backend engineer", "India"),
    ("fastapi engineer", "India"),
    # AI / LLM — fast-growing, relevant
    ("ai engineer", "India"),
    ("llm engineer", "India"),
    ("ml engineer", "India"),
    ("machine learning engineer", "India"),
    ("ai backend engineer", "India"),
    ("generative ai engineer", "India"),
    # City-level — different postings surface per city
    ("backend engineer", "Bangalore, Karnataka, India"),
    ("software engineer", "Bangalore, Karnataka, India"),
    ("backend developer", "Bangalore, Karnataka, India"),
    ("golang", "Bangalore, Karnataka, India"),
    ("python developer", "Bangalore, Karnataka, India"),
    ("ai engineer", "Bangalore, Karnataka, India"),
    ("backend engineer", "Delhi, India"),
    ("software engineer", "Delhi, India"),
    ("backend engineer", "Gurugram, Haryana, India"),
    ("software engineer", "Gurugram, Haryana, India"),
    ("backend engineer", "Mumbai, Maharashtra, India"),
    ("software engineer", "Hyderabad, Telangana, India"),
    ("backend engineer", "Hyderabad, Telangana, India"),
    ("backend engineer", "Pune, Maharashtra, India"),
    ("software engineer", "Noida, Uttar Pradesh, India"),
    # Remote / global roles that hire India
    ("backend engineer", "Remote"),
    ("software engineer", "Remote"),
    ("backend engineer", "Worldwide"),
]


async def fetch_postings(
    queries: list[tuple[str, str]] | None = None,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """
    Search LinkedIn for backend/AI jobs in India.
    Each query is a (keyword, location) tuple.
    Returns normalized posting dicts.
    """
    queries = queries or INDIA_QUERIES
    seen: set[str] = set()
    results: list[dict] = []

    async with httpx.AsyncClient(
        timeout=20.0, headers=HEADERS, follow_redirects=True
    ) as client:
        for keyword, location in queries:
            for page in range(max_pages):
                start = page * PAGE_SIZE
                postings = await _fetch_page(client, keyword, location, start)
                new = 0
                for p in postings:
                    if p["dedup_hash"] not in seen:
                        seen.add(p["dedup_hash"])
                        results.append(p)
                        new += 1
                if len(postings) < PAGE_SIZE or new == 0:
                    break
                await asyncio.sleep(DELAY_BETWEEN_REQUESTS)

    logger.info(f"LinkedIn: fetched {len(results)} unique postings")
    return results


async def _fetch_page(
    client: httpx.AsyncClient,
    keywords: str,
    location: str,
    start: int,
) -> list[dict]:
    params = {
        "keywords": keywords,
        "location": location,
        "start": start,
        "count": PAGE_SIZE,
        "f_TPR": "r604800",  # last 7 days
    }
    try:
        resp = await client.get(GUEST_SEARCH, params=params)
        if resp.status_code == 429:
            logger.warning("LinkedIn rate limited — backing off 30s")
            await asyncio.sleep(30)
            return []
        if resp.status_code != 200:
            logger.warning(f"LinkedIn search returned {resp.status_code} for '{keywords}' @ {location}")
            return []
        html = resp.text
    except Exception as e:
        logger.error(f"LinkedIn fetch failed for '{keywords}' @ {location}: {e}")
        return []

    return _parse_job_cards(html, location)


def _parse_job_cards(html: str, location_hint: str) -> list[dict]:
    """
    LinkedIn guest API returns HTML job cards.
    Extract all fields globally then zip by position — more reliable than
    splitting by card since nested divs break per-card regex boundaries.
    """
    job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
    titles = [
        _strip_tags(m)
        for m in re.findall(r'class="base-search-card__title"[^>]*>\s*(.*?)\s*</h3>', html, re.DOTALL)
    ]
    companies = [
        _strip_tags(m)
        for m in re.findall(
            r'class="base-search-card__subtitle"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL
        )
    ]
    locations = [
        _strip_tags(m)
        for m in re.findall(r'class="job-search-card__location"[^>]*>(.*?)</span>', html, re.DOTALL)
    ]
    dates = re.findall(r'datetime="([^"]+)"', html)

    results = []
    for i, job_id in enumerate(job_ids):
        title = titles[i] if i < len(titles) else ""
        company = companies[i] if i < len(companies) else ""
        location = locations[i] if i < len(locations) else location_hint
        url = f"https://www.linkedin.com/jobs/view/{job_id}"

        posted_at: datetime | None = None
        if i < len(dates):
            try:
                posted_at = datetime.fromisoformat(dates[i].replace("Z", "+00:00"))
            except Exception:
                pass

        if not title:
            continue

        dedup_hash = hashlib.sha256(f"linkedin:{job_id}".encode()).hexdigest()
        results.append({
            "external_id": job_id,
            "title": title,
            "company_name": company,
            "location": location,
            "apply_url": url,
            "content_text": f"{title} {company} {location}",
            "raw_json": {"job_id": job_id, "title": title, "company": company, "location": location, "url": url},
            "dedup_hash": dedup_hash,
            "posted_at": posted_at,
            "salary_min": None,
            "salary_max": None,
            "source": "linkedin",
        })

    return results


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()
