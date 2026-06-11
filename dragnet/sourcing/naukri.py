"""
Naukri.com job search scraper.
Uses Browserbase + Stagehand — Naukri's API requires recaptcha and their
pages are fully client-side rendered, so a real browser is the only reliable path.

Scrapes Naukri's search result pages for backend/AI engineering roles in India.
Each search URL is a static SSR page on naukri.com/{keyword}-jobs.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Pre-built Naukri search URLs — these SSR pages render job listings server-side.
# URL format: naukri.com/{keyword}-jobs?experience={min}-{max}
SEARCH_URLS = [
    "https://www.naukri.com/backend-engineer-jobs",
    "https://www.naukri.com/software-engineer-jobs-in-bangalore",
    "https://www.naukri.com/software-engineer-jobs-in-delhi-ncr",
    "https://www.naukri.com/python-developer-jobs",
    "https://www.naukri.com/golang-developer-jobs",
    "https://www.naukri.com/ai-engineer-jobs",
    "https://www.naukri.com/machine-learning-engineer-jobs",
]

# Stagehand extraction schema for a single job card
JOB_EXTRACT_INSTRUCTION = """
Extract all visible job listings on this page. For each job return:
- title: the job title
- company: the company name
- location: city / location
- experience: experience required (e.g., "2-5 years")
- salary: salary range if shown
- url: the link to the full job listing (the href of the job title link)
- job_id: any numeric ID visible in the URL or data attributes
Return as a list of jobs.
"""


async def fetch_postings(max_pages_per_url: int = 2) -> list[dict]:
    """
    Scrape Naukri for backend/AI jobs.
    Falls back to empty list if Browserbase credentials are not configured.
    """
    try:
        from dragnet.executor.session import BrowserSession
        from dragnet.config import settings
        _ = settings.browserbase_api_key  # will raise if not set
    except Exception:
        logger.warning(
            "Naukri sourcing skipped — BROWSERBASE_API_KEY not configured. "
            "Set it in .env to enable Naukri scraping."
        )
        return []

    seen: set[str] = set()
    results: list[dict] = []

    for search_url in SEARCH_URLS:
        try:
            jobs = await _scrape_url(search_url)
            for j in jobs:
                if j["dedup_hash"] not in seen:
                    seen.add(j["dedup_hash"])
                    results.append(j)
        except Exception as e:
            logger.error(f"Naukri scrape failed for {search_url}: {e}")
            continue

    logger.info(f"Naukri: fetched {len(results)} unique postings")
    return results


async def _scrape_url(url: str) -> list[dict]:
    from dragnet.executor.session import BrowserSession

    async with BrowserSession() as session:
        await session.goto(url)
        # Wait for job cards to render
        await session.page.wait_for_timeout(3000)

        # Try structured extraction first
        jobs_raw = await _extract_with_stagehand(session)
        if jobs_raw:
            return [_normalize(j, url) for j in jobs_raw if j.get("title")]

        # Fallback: direct HTML parsing after JS render
        html = await session.page.content()
        return _parse_rendered_html(html, url)


async def _extract_with_stagehand(session) -> list[dict]:
    """Use Stagehand's LLM extraction to pull structured job data."""
    try:
        result = await session.extract(JOB_EXTRACT_INSTRUCTION)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "jobs" in result:
            return result["jobs"]
    except Exception as e:
        logger.debug(f"Stagehand extraction failed, falling back to HTML parse: {e}")
    return []


def _parse_rendered_html(html: str, source_url: str) -> list[dict]:
    """Parse job cards from Naukri's rendered HTML."""
    results = []

    # Job title links — Naukri uses <a class="title"> inside article.jobTuple
    title_pattern = re.compile(
        r'<a[^>]+href="(https://www\.naukri\.com/job-listings-[^"]+)"[^>]*>\s*([^<]+)\s*</a>',
        re.DOTALL,
    )
    company_pattern = re.compile(
        r'<a[^>]+class="[^"]*subTitle[^"]*"[^>]*>\s*([^<]+)\s*</a>', re.DOTALL
    )
    location_pattern = re.compile(
        r'<span[^>]+class="[^"]*locWdth[^"]*"[^>]*>\s*([^<]+)\s*</span>', re.DOTALL
    )

    titles = title_pattern.findall(html)
    companies = [m.strip() for m in company_pattern.findall(html)]
    locations = [m.strip() for m in location_pattern.findall(html)]

    for i, (apply_url, title) in enumerate(titles):
        job_id = re.search(r'job-listings-(.+?)(?:\?|$)', apply_url)
        job_id_str = job_id.group(1) if job_id else f"naukri-{i}"
        results.append(_normalize({
            "title": title.strip(),
            "company": companies[i] if i < len(companies) else "",
            "location": locations[i] if i < len(locations) else "",
            "url": apply_url,
            "job_id": job_id_str,
        }, source_url))

    return results


def _normalize(job: dict, source_url: str = "") -> dict:
    title = (job.get("title") or "").strip()
    company_name = (job.get("company") or "").strip()
    location = (job.get("location") or "").strip()
    apply_url = job.get("url") or job.get("apply_url") or source_url
    job_id = str(job.get("job_id") or apply_url)

    content_text = " ".join(filter(None, [title, company_name, location, job.get("experience", "")]))
    dedup_hash = hashlib.sha256(f"naukri:{job_id}".encode()).hexdigest()

    return {
        "external_id": job_id,
        "title": title,
        "company_name": company_name,
        "location": location,
        "apply_url": apply_url,
        "content_text": content_text,
        "raw_json": {
            "title": title,
            "company": company_name,
            "location": location,
            "experience": job.get("experience", ""),
            "salary": job.get("salary", ""),
            "url": apply_url,
            "source_url": source_url,
        },
        "dedup_hash": dedup_hash,
        "posted_at": None,
        "salary_min": None,
        "salary_max": None,
        "source": "naukri",
    }
