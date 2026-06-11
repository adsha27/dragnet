"""
Hacker News "Who is Hiring" monthly thread scraper.

Uses the official HN Algolia API — no browser needed.
The monthly thread title is always "Ask HN: Who is hiring? (Month Year)".
Extracts top-level comments (each = one job posting) and parses structured fields.
"""

import asyncio
import hashlib
import logging
import re

import httpx

logger = logging.getLogger(__name__)

HN_ALGOLIA = "https://hn.algolia.com/api/v1"

RELEVANT_ROLE_RE = re.compile(
    r"\b(backend|software\s+engineer|sde|swe|platform|ai\s+engineer|ml\s+engineer|"
    r"machine\s+learning|llm|generative\s+ai|full.?stack|fullstack|data\s+engineer|"
    r"golang|go\s+developer|python\s+developer|devops|sre)\b",
    re.IGNORECASE,
)

REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
ONSITE_RE = re.compile(r"\b(onsite|on.site|in.office|hybrid)\b", re.IGNORECASE)
INDIA_RE = re.compile(r"\b(india|bangalore|bengaluru|delhi|hyderabad|mumbai|pune|noida|gurgaon)\b", re.IGNORECASE)

# Reject comments that are clearly not relevant
REJECT_RE = re.compile(
    r"\b(looking\s+for\s+work|seeking\s+opportunities|freelance\s+available|"
    r"available\s+for\s+hire|job\s+seeker)\b",
    re.IGNORECASE,
)


async def fetch_postings(month_lookback: int = 2) -> list[dict]:
    """
    Fetch job postings from the most recent HN Who is Hiring threads.
    month_lookback: how many recent threads to search (default=2).
    Returns list of structured job dicts.
    """
    thread_ids = await _find_hiring_thread_ids(month_lookback)
    if not thread_ids:
        logger.warning("No HN hiring threads found")
        return []

    all_postings: list[dict] = []
    seen: set[str] = set()

    for thread_id in thread_ids:
        postings = await _fetch_thread_comments(thread_id)
        for p in postings:
            if p["dedup_hash"] not in seen:
                seen.add(p["dedup_hash"])
                all_postings.append(p)
        await asyncio.sleep(0.5)

    logger.info(f"HN hiring: {len(all_postings)} postings from {len(thread_ids)} threads")
    return all_postings


async def _find_hiring_thread_ids(count: int) -> list[str]:
    """Search Algolia for recent 'Who is hiring' Ask HN threads."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"{HN_ALGOLIA}/search",
                params={
                    "query": "Ask HN: Who is hiring",
                    "tags": "ask_hn",
                    "numericFilters": "points>50",
                    "hitsPerPage": count,
                },
            )
            r.raise_for_status()
            hits = r.json().get("hits", [])
            return [h["objectID"] for h in hits if "who is hiring" in h.get("title", "").lower()]
    except Exception as e:
        logger.error(f"HN thread search failed: {e}")
        return []


async def _fetch_thread_comments(thread_id: str) -> list[dict]:
    """Fetch all top-level comments from an HN thread via Algolia."""
    postings: list[dict] = []
    page = 0

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            while True:
                r = await c.get(
                    f"{HN_ALGOLIA}/search",
                    params={
                        "tags": f"comment,story_{thread_id}",
                        "hitsPerPage": 100,
                        "page": page,
                    },
                )
                r.raise_for_status()
                data = r.json()
                hits = data.get("hits", [])
                if not hits:
                    break

                for hit in hits:
                    # Only top-level comments (direct replies to the thread)
                    if hit.get("parent_id") != int(thread_id):
                        continue
                    parsed = _parse_comment(hit)
                    if parsed:
                        postings.append(parsed)

                if page >= data.get("nbPages", 1) - 1:
                    break
                page += 1
                await asyncio.sleep(0.3)

    except Exception as e:
        logger.error(f"HN thread {thread_id} fetch failed: {e}")

    return postings


def _parse_comment(hit: dict) -> dict | None:
    """Parse an HN job comment into a structured posting."""
    import html
    text = hit.get("comment_text", "") or ""
    # Strip HTML tags then unescape entities
    clean = html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()

    if not clean or len(clean) < 50:
        return None

    # Filter out job-seeker posts
    if REJECT_RE.search(clean):
        return None

    # Must match a relevant role keyword
    if not RELEVANT_ROLE_RE.search(clean):
        return None

    # Extract company name — first line of the comment often starts with "Company | Role | Location"
    first_line = clean.split("\n")[0][:200]
    company = _extract_company(first_line)
    title = _extract_title(first_line, clean)
    location = _extract_location(first_line, clean)

    # Location filter: accept remote, India, or unspecified
    is_remote = bool(REMOTE_RE.search(clean))
    is_india = bool(INDIA_RE.search(clean))
    is_onsite_non_india = bool(ONSITE_RE.search(clean)) and not is_india and not is_remote

    if is_onsite_non_india:
        return None

    hn_url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
    dedup = hashlib.sha256(f"hn:{hit['objectID']}".encode()).hexdigest()

    return {
        "id": hit["objectID"],
        "source": "hn_hiring",
        "company_name": company,
        "title": title,
        "location": location,
        "remote": is_remote,
        "india_eligible": is_india or is_remote,
        "content_text": clean[:3000],
        "apply_url": hn_url,
        "job_url": hn_url,
        "dedup_hash": dedup,
        "created_at": hit.get("created_at", ""),
    }


def _extract_company(line: str) -> str:
    """Extract company name from 'Company | Role | Location' pattern."""
    # Try pipe-separated first
    parts = [p.strip() for p in re.split(r"\s*[|/]\s*", line) if p.strip()]
    if parts:
        candidate = re.sub(r"\(.*?\)", "", parts[0]).strip()
        if 1 < len(candidate) < 60:
            return candidate
    # Fallback: first word cluster
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9\s\.\-]{1,40}?)(?:\s*[\|\(,]|\s{2,})", line)
    return m.group(1).strip() if m else "Unknown"


def _extract_title(first_line: str, full_text: str) -> str:
    """Extract job title from first line or full text."""
    parts = [p.strip() for p in re.split(r"\s*[|/]\s*", first_line)]
    for part in parts[1:3]:
        if RELEVANT_ROLE_RE.search(part):
            return part[:100]
    # Search full text for a role line
    m = RELEVANT_ROLE_RE.search(full_text)
    if m:
        start = max(0, m.start() - 20)
        return full_text[start : m.end() + 30].strip()[:100]
    return parts[1][:100] if len(parts) > 1 else "Software Engineer"


def _extract_location(first_line: str, full_text: str) -> str:
    """Extract location from first line or full text."""
    parts = [p.strip() for p in re.split(r"\s*[|/]\s*", first_line)]
    for part in parts:
        if REMOTE_RE.search(part) or INDIA_RE.search(part):
            return part[:80]
    m = re.search(r"\b(Remote|Bangalore|Bengaluru|Delhi|Hyderabad|Mumbai|Pune|Noida|Gurgaon)\b", full_text, re.IGNORECASE)
    return m.group(0) if m else "Unknown"
