"""
Reddit referral thread scraper.
Uses Reddit's public JSON API (no auth, append .json to any URL).

Targets weekly referral megathreads on:
- r/developersIndia
- r/cscareerquestions
- r/IndiaTechCommunity

Extracts structured referral offers: company, role, who to contact (DM them on Reddit).
Output is a list of referral opportunities — not job postings, but direct human contacts.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "dragnet-job-hunter/1.0 (personal job search tool)"
BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}
OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_API_BASE = "https://oauth.reddit.com"

SUBREDDITS = [
    {
        "sub": "developersIndia",
        "search_query": "referral",
        "type": "search",
    },
    {
        "sub": "developersIndia",
        "search_query": "referral megathread",
        "type": "search",
    },
    {
        "sub": "cscareerquestions",
        "search_query": "referral megathread",
        "type": "search",
    },
    {
        "sub": "IndiaTechCommunity",
        "search_query": "referral",
        "type": "search",
    },
]

TECH_COMPANIES = {
    "google", "microsoft", "amazon", "meta", "apple", "netflix", "uber", "stripe",
    "razorpay", "cred", "swiggy", "zomato", "meesho", "phonepe", "paytm", "flipkart",
    "myntra", "groww", "zerodha", "browserstack", "freshworks", "zoho", "chargebee",
    "postman", "hasura", "setu", "niyo", "slice", "jupiter", "fi", "cred", "ofbusiness",
    "darwinbox", "leadsquared", "druva", "icertis", "mindtickle", "moengage",
    "clevertap", "appsflyer", "gupshup", "kaleyra", "tanla",
    "openai", "anthropic", "cohere", "mistral", "databricks", "snowflake",
    "cloudflare", "vercel", "hashicorp", "gitlab", "atlassian", "twilio",
}

ROLE_PATTERNS = re.compile(
    r"\b(backend|software\s+engineer|sde[\s\-]?\d?|swe|platform|ai\s+engineer|"
    r"ml\s+engineer|machine\s+learning|llm|fullstack|full.stack|data\s+engineer|"
    r"devops|sre|frontend)\b",
    re.IGNORECASE,
)

COMPANY_PATTERN = re.compile(
    r"\b(?:at\s+|@\s*|for\s+|in\s+)([A-Z][A-Za-z0-9\.\-]+(?:\s+[A-Z][A-Za-z0-9]+)*)\b"
)


async def _get_oauth_token() -> str | None:
    """Get Reddit OAuth token using client_credentials grant (read-only, no user needed)."""
    from dragnet.config import settings
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            OAUTH_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        return resp.json().get("access_token")


async def fetch_referral_opportunities() -> list[dict]:
    """
    Pull active referral opportunities from Reddit megathreads.
    Requires REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET in .env
    (register a free script app at reddit.com/prefs/apps).
    Returns structured offers with company, role, Reddit username to DM.
    """
    token = await _get_oauth_token()
    if not token:
        logger.warning(
            "Reddit sourcing skipped — REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set. "
            "Register a free app at reddit.com/prefs/apps (script type) and add creds to .env."
        )
        return []

    headers = {**BASE_HEADERS, "Authorization": f"Bearer {token}"}
    seen: set[str] = set()
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=20.0, headers=headers, base_url=OAUTH_API_BASE) as client:
        for cfg in SUBREDDITS:
            try:
                threads = await _fetch_threads(client, cfg)
                for thread in threads:
                    offers = await _extract_offers_from_thread(client, thread)
                    for offer in offers:
                        if offer["dedup_hash"] not in seen:
                            seen.add(offer["dedup_hash"])
                            results.append(offer)
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Reddit fetch failed for r/{cfg['sub']}: {e}")
                continue

    logger.info(f"Reddit: {len(results)} referral opportunities found")
    return results


async def _fetch_threads(client: httpx.AsyncClient, cfg: dict) -> list[dict]:
    sub = cfg["sub"]
    q = cfg["search_query"]
    resp = await client.get(
        f"/r/{sub}/search",
        params={"q": q, "sort": "new", "restrict_sr": "1", "limit": 10, "t": "month"},
    )
    resp.raise_for_status()
    posts = resp.json().get("data", {}).get("children", [])
    return [p["data"] for p in posts if p.get("data", {}).get("num_comments", 0) > 0]


async def _extract_offers_from_thread(client: httpx.AsyncClient, thread: dict) -> list[dict]:
    thread_id = thread.get("id", "")
    sub = thread.get("subreddit", "")
    thread_title = thread.get("title", "")
    thread_url = f"https://reddit.com{thread.get('permalink', '')}"

    # Fetch comments via OAuth API
    try:
        resp = await client.get(
            f"/r/{sub}/comments/{thread_id}",
            params={"limit": 200, "depth": 2},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"Failed to fetch comments for {thread_id}: {e}")
        return []

    offers = []
    if not isinstance(data, list) or len(data) < 2:
        return []

    comments = data[1].get("data", {}).get("children", [])
    for comment in comments:
        cdata = comment.get("data", {})
        body = cdata.get("body", "")
        author = cdata.get("author", "")
        created = cdata.get("created_utc")

        if not body or author in ("[deleted]", "AutoModerator", ""):
            continue

        # Only process comments that look like referral offers
        lower = body.lower()
        if not any(kw in lower for kw in ["referral", "refer", "dm me", "pm me", "message me"]):
            continue

        parsed = _parse_referral_comment(body, author, thread_url, thread_title)
        if parsed:
            offers.append(parsed)

    return offers


def _parse_referral_comment(body: str, author: str, thread_url: str, thread_title: str) -> dict | None:
    lower = body.lower()

    # Extract company mentions
    companies_found = []
    for company in TECH_COMPANIES:
        if company in lower:
            companies_found.append(company.title())

    # Regex for capitalized company names
    cap_matches = COMPANY_PATTERN.findall(body)
    for m in cap_matches:
        if len(m) > 2 and m not in ("I", "DM", "PM", "For", "At"):
            companies_found.append(m)

    # Extract role mentions
    role_matches = ROLE_PATTERNS.findall(body)
    roles = list(set(r.strip() for r in role_matches))

    company = ", ".join(set(companies_found)) if companies_found else "Unknown"
    role = ", ".join(set(roles)) if roles else "Software Engineer"

    # Generate dedup hash on author + first 100 chars of body
    dedup_str = f"reddit:{author}:{body[:100]}"
    dedup_hash = hashlib.sha256(dedup_str.encode()).hexdigest()

    contact_url = f"https://reddit.com/u/{author}"

    return {
        "type": "referral",
        "source": "reddit",
        "company": company,
        "role": role,
        "contact_name": f"u/{author}",
        "contact_url": contact_url,
        "thread_url": thread_url,
        "thread_title": thread_title,
        "body_preview": body[:300],
        "how_to_contact": f"DM u/{author} on Reddit: {contact_url}",
        "dedup_hash": dedup_hash,
    }
