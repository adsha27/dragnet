"""
Reddit referral thread scraper.

Two modes (tried in order):
1. OAuth API — fastest, if REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET are in .env
2. Stagehand/Browserbase — browser-based fallback, needs BROWSERBASE_API_KEY

Targets weekly referral megathreads on r/developersIndia and r/cscareerquestions.
Extracts structured offers: company, role, Reddit username to DM.
"""

import asyncio
import hashlib
import logging
import re

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "dragnet/1.0 (personal use)"
OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE = "https://oauth.reddit.com"

SEARCH_TARGETS = [
    ("developersIndia", "referral megathread"),
    ("developersIndia", "referral"),
    ("cscareerquestions", "referral megathread"),
    ("IndiaTechCommunity", "referral"),
]

BROWSER_SEARCH_URLS = [
    "https://www.reddit.com/r/developersIndia/search/?q=referral+megathread&sort=new&restrict_sr=1&t=month",
    "https://www.reddit.com/r/cscareerquestions/search/?q=referral+megathread&sort=new&restrict_sr=1&t=month",
    "https://www.reddit.com/r/IndiaTechCommunity/search/?q=referral&sort=new&restrict_sr=1&t=month",
]

TECH_COMPANIES = {
    "google", "microsoft", "amazon", "meta", "apple", "netflix", "uber", "stripe",
    "razorpay", "cred", "swiggy", "zomato", "meesho", "phonepe", "paytm", "flipkart",
    "myntra", "groww", "zerodha", "browserstack", "freshworks", "zoho", "chargebee",
    "postman", "hasura", "setu", "niyo", "slice", "jupiter", "fi", "ofbusiness",
    "darwinbox", "leadsquared", "druva", "icertis", "mindtickle", "moengage",
    "clevertap", "appsflyer", "gupshup", "openai", "anthropic", "cohere",
    "cloudflare", "vercel", "hashicorp", "gitlab", "atlassian", "twilio",
    "nvidia", "adobe", "salesforce", "oracle", "sap", "infosys", "wipro", "tcs",
}

ROLE_RE = re.compile(
    r"\b(backend|software\s+engineer|sde[\s\-]?\d?|swe|platform|ai\s+engineer|"
    r"ml\s+engineer|machine\s+learning|llm|fullstack|full.stack|data\s+engineer|"
    r"devops|sre|frontend|python|golang|go\s+developer)\b",
    re.IGNORECASE,
)
COMPANY_RE = re.compile(
    r"\b(?:at\s+|@\s*|for\s+)([A-Z][A-Za-z0-9\.\-]+(?:\s+[A-Z][A-Za-z0-9]+)*)\b"
)


async def fetch_referral_opportunities() -> list[dict]:
    """Try OAuth first, fall back to Stagehand."""
    results = await _fetch_via_oauth()
    if results:
        return results
    return await _fetch_via_browser()


# ── OAuth path ────────────────────────────────────────────────────────────────

async def _fetch_via_oauth() -> list[dict]:
    from dragnet.config import settings
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        return []

    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                OAUTH_TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(settings.reddit_client_id, settings.reddit_client_secret),
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
            token = r.json().get("access_token")
    except Exception as e:
        logger.warning(f"Reddit OAuth token failed: {e}")
        return []

    headers = {"User-Agent": USER_AGENT, "Authorization": f"Bearer {token}"}
    seen: set[str] = set()
    results: list[dict] = []

    async with httpx.AsyncClient(timeout=20, headers=headers, base_url=OAUTH_BASE) as client:
        for sub, query in SEARCH_TARGETS:
            try:
                r = await client.get(
                    f"/r/{sub}/search",
                    params={"q": query, "sort": "new", "restrict_sr": "1", "limit": 10, "t": "month"},
                )
                r.raise_for_status()
                posts = r.json().get("data", {}).get("children", [])
                threads = [p["data"] for p in posts if p.get("data", {}).get("num_comments", 0) > 2]

                for thread in threads:
                    thread_id = thread.get("id", "")
                    permalink = thread.get("permalink", "")
                    cr = await client.get(f"/r/{sub}/comments/{thread_id}", params={"limit": 200, "depth": 2})
                    cr.raise_for_status()
                    data = cr.json()
                    if isinstance(data, list) and len(data) >= 2:
                        comments = data[1].get("data", {}).get("children", [])
                        for offer in _parse_comments(comments, f"https://reddit.com{permalink}", thread.get("title", "")):
                            if offer["dedup_hash"] not in seen:
                                seen.add(offer["dedup_hash"])
                                results.append(offer)

                await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Reddit OAuth fetch failed r/{sub}: {e}")

    logger.info(f"Reddit (OAuth): {len(results)} referral opportunities")
    return results


# ── Stagehand/browser path ────────────────────────────────────────────────────

async def _fetch_via_browser() -> list[dict]:
    try:
        from dragnet.executor.session import BrowserSession
        from dragnet.config import settings
        _ = settings.browserbase_api_key
    except Exception:
        logger.warning(
            "Reddit sourcing skipped — no OAuth credentials and no BROWSERBASE_API_KEY. "
            "Add REDDIT_CLIENT_ID/SECRET or BROWSERBASE_API_KEY to .env."
        )
        return []

    from dragnet.executor.session import BrowserSession
    seen: set[str] = set()
    results: list[dict] = []

    for search_url in BROWSER_SEARCH_URLS:
        try:
            async with BrowserSession() as session:
                await session.goto(search_url)
                await session.page.wait_for_timeout(3000)

                # Extract post links from search results
                post_links = await session.page.evaluate("""() => {
                    const links = [...document.querySelectorAll('a[href*="/comments/"]')];
                    return [...new Set(links.map(a => a.href))].slice(0, 8);
                }""")

                for post_url in post_links:
                    try:
                        await session.goto(post_url)
                        await session.page.wait_for_timeout(2000)

                        title = await session.page.title()
                        comments_text = await session.page.evaluate("""() => {
                            const items = [...document.querySelectorAll('[data-testid="comment"]')];
                            return items.slice(0, 100).map(el => ({
                                text: el.innerText?.slice(0, 500) || '',
                                author: el.querySelector('a[href*="/user/"]')?.innerText || ''
                            }));
                        }""")

                        for comment in (comments_text or []):
                            body = comment.get("text", "")
                            author = comment.get("author", "").lstrip("u/")
                            if not body or not author:
                                continue
                            lower = body.lower()
                            if not any(kw in lower for kw in ["referral", "refer", "dm me", "pm me"]):
                                continue
                            offer = _make_offer(body, author, post_url, title)
                            if offer["dedup_hash"] not in seen:
                                seen.add(offer["dedup_hash"])
                                results.append(offer)

                        await asyncio.sleep(1.5)
                    except Exception as e:
                        logger.debug(f"Reddit post scrape failed {post_url}: {e}")

        except Exception as e:
            logger.error(f"Reddit browser fetch failed for {search_url}: {e}")

    logger.info(f"Reddit (browser): {len(results)} referral opportunities")
    return results


# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_comments(comments: list, thread_url: str, title: str) -> list[dict]:
    results = []
    for comment in comments:
        cdata = comment.get("data", {})
        body = cdata.get("body", "")
        author = cdata.get("author", "")
        if not body or author in ("[deleted]", "AutoModerator", ""):
            continue
        lower = body.lower()
        if not any(kw in lower for kw in ["referral", "refer", "dm me", "pm me", "message me"]):
            continue
        results.append(_make_offer(body, author, thread_url, title))
    return results


def _make_offer(body: str, author: str, thread_url: str, thread_title: str) -> dict:
    lower = body.lower()
    companies = [c.title() for c in TECH_COMPANIES if c in lower]
    cap = [m for m in COMPANY_RE.findall(body) if len(m) > 2 and m not in ("I", "DM", "PM")]
    companies = list(set(companies + cap))
    roles = list(set(ROLE_RE.findall(body)))
    return {
        "type": "referral",
        "source": "reddit",
        "company": ", ".join(companies) if companies else "Unknown",
        "role": ", ".join(roles) if roles else "Software Engineer",
        "contact_name": f"u/{author}",
        "contact_url": f"https://reddit.com/u/{author}",
        "thread_url": thread_url,
        "thread_title": thread_title,
        "body_preview": body[:300],
        "how_to_contact": f"DM u/{author} on Reddit: https://reddit.com/u/{author}",
        "dedup_hash": hashlib.sha256(f"reddit:{author}:{body[:100]}".encode()).hexdigest(),
    }
