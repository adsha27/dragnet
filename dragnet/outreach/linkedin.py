"""
LinkedIn outreach — find CTOs/engineering leads, generate personalized messages,
send connection requests via Stagehand.

Rate limit: 10 connection requests/day max (LinkedIn flags automation above this).
Message format: 300 chars max (LinkedIn connection note limit).

Flow:
  1. find_linkedin_contacts(company_name) → list of {name, title, linkedin_url}
  2. compose_linkedin_note(contact, company) → 300-char personalized note
  3. send_connection_request(linkedin_url, note) → bool via Stagehand
  4. process_outreach_queue(db, limit=10) → runs the full pipeline on queued companies
"""

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.config import settings
from dragnet.llm import complete
from dragnet.db.models import Company, FounderContact, OutreachEmail
from dragnet.tailoring.facts import facts_as_context_string

logger = logging.getLogger(__name__)

MAX_PER_DAY = 10  # Connection requests per day — stay well below LinkedIn's limit

SYSTEM_PROMPT = """You write LinkedIn connection request notes for a job candidate.

Hard constraints:
- MAX 300 characters (LinkedIn's limit). Count carefully.
- No greetings ("Hi", "Hello", "Dear"). Start with the substance.
- No filler ("I'm excited", "I came across", "I'd love to").
- Reference something SPECIFIC about their company or role — not generic.
- End with one clear ask: exploring opportunities, 15-min call.
- Use only facts from the provided fact sheet.
- Write like a human, not a recruiter.

Good example (280 chars):
Built an AI agent platform handling 50k tool calls/day — MCP + RAG on Go/FastAPI.
Saw your team is building [X]. Interested in whether there's a backend/AI fit.
Happy to share the repo. Open to a quick call if useful.

Return only the note text. Nothing else."""


async def find_linkedin_contacts(company_name: str, domain: str = "") -> list[dict]:
    """
    Use Exa to find LinkedIn profiles of CTOs / eng leads at a company.
    Returns [{name, title, linkedin_url}]
    """
    try:
        from exa_py import Exa
        client = Exa(api_key=settings.exa_api_key)
    except Exception as e:
        logger.error(f"Exa init failed: {e}")
        return []

    targets = []
    queries = [
        f'site:linkedin.com/in "{company_name}" CTO OR "Head of Engineering" OR "VP Engineering"',
        f'site:linkedin.com/in "{company_name}" founder engineer',
        f'site:linkedin.com/in "{company_name}" "Engineering Manager" OR "Tech Lead"',
    ]

    seen_urls: set[str] = set()
    for query in queries:
        try:
            resp = client.search(query, num_results=3, type="neural")
            for item in resp.results:
                url = item.url or ""
                if "linkedin.com/in/" not in url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = _infer_title_from_url_and_text(url, item.title or "")
                name = _infer_name_from_url(url)
                targets.append({
                    "name": name,
                    "title": title,
                    "linkedin_url": url,
                    "company": company_name,
                })
        except Exception as e:
            logger.warning(f"Exa LinkedIn search failed for {company_name}: {e}")

    return targets[:5]


async def compose_linkedin_note(contact: dict, company_name: str, company_desc: str = "") -> str:
    """Generate a ≤300-char personalized connection request note."""
    facts_context = facts_as_context_string()

    prompt = f"""TARGET:
Name: {contact.get('name', 'Hiring Lead')}
Title: {contact.get('title', 'Engineering Lead')}
Company: {company_name}
Company context: {company_desc or 'No additional context'}

CANDIDATE FACTS:
{facts_context}

Write the LinkedIn connection note now (max 300 characters)."""

    try:
        note = await complete(SYSTEM_PROMPT, prompt, max_tokens=150)
        text = note.content.strip()
        # Hard trim to 300 chars at a sentence boundary if possible
        if len(text) > 300:
            text = text[:297] + "..."
        return text
    except Exception as e:
        logger.error(f"Note composition failed: {e}")
        return ""


async def send_connection_request(linkedin_url: str, note: str) -> bool:
    """
    Use Stagehand/Browserbase to navigate to a LinkedIn profile and send a connection
    request with the given note.

    Requires BROWSERBASE_API_KEY + a LinkedIn session cookie (set via Stagehand manually first).
    Returns True if sent successfully.
    """
    try:
        from dragnet.executor.session import BrowserSession
        _ = settings.browserbase_api_key
    except Exception:
        logger.warning("Stagehand not configured — connection request skipped. Set BROWSERBASE_API_KEY.")
        return False

    try:
        from dragnet.executor.session import BrowserSession
        async with BrowserSession() as session:
            await session.goto(linkedin_url)
            await session.page.wait_for_timeout(2000)

            # Find and click Connect button
            clicked = await session.page.evaluate("""() => {
                const btns = [...document.querySelectorAll('button')];
                const connect = btns.find(b => b.innerText.trim() === 'Connect');
                if (connect) { connect.click(); return true; }
                return false;
            }""")

            if not clicked:
                # Try "More" dropdown → Connect
                await session.page.evaluate("""() => {
                    const more = [...document.querySelectorAll('button')].find(b => b.innerText.includes('More'));
                    if (more) more.click();
                }""")
                await session.page.wait_for_timeout(800)
                await session.page.evaluate("""() => {
                    const items = [...document.querySelectorAll('[data-test-overflow-list-item]')];
                    const connect = items.find(i => i.innerText.includes('Connect'));
                    if (connect) connect.click();
                }""")

            await session.page.wait_for_timeout(1000)

            # "Add a note" button
            await session.page.evaluate("""() => {
                const btns = [...document.querySelectorAll('button')];
                const addNote = btns.find(b => b.innerText.includes('Add a note'));
                if (addNote) addNote.click();
            }""")
            await session.page.wait_for_timeout(500)

            # Type the note
            textarea = await session.page.query_selector("textarea#custom-message")
            if not textarea:
                textarea = await session.page.query_selector("textarea[name='message']")

            if textarea:
                await textarea.fill(note)

            # Send
            await session.page.evaluate("""() => {
                const btns = [...document.querySelectorAll('button')];
                const send = btns.find(b => b.innerText.trim() === 'Send' || b.innerText.includes('Send now'));
                if (send) send.click();
            }""")
            await session.page.wait_for_timeout(1500)
            logger.info(f"Connection request sent to {linkedin_url}")
            return True

    except Exception as e:
        logger.error(f"Connection request failed for {linkedin_url}: {e}")
        return False


async def sent_today(db: AsyncSession) -> int:
    today = date.today()
    result = await db.execute(
        select(func.count()).select_from(OutreachEmail).where(
            OutreachEmail.channel == "linkedin",
            func.date(OutreachEmail.sent_at) == today,
            OutreachEmail.sent_at.is_not(None),
        )
    )
    return result.scalar() or 0


async def process_outreach_queue(db: AsyncSession, limit: int = MAX_PER_DAY) -> int:
    """
    Find top-ranked eligible companies that haven't been contacted on LinkedIn yet,
    find their engineering leads, compose notes, and send requests.
    Returns number of requests sent.
    """
    today_count = await sent_today(db)
    remaining = limit - today_count
    if remaining <= 0:
        logger.info(f"LinkedIn daily limit ({limit}) already reached")
        return 0

    # Pull companies ranked but not yet LinkedIn-contacted
    result = await db.execute(
        select(Company)
        .where(
            Company.rank_score.is_not(None),
            Company.linkedin_contacted_at.is_(None),
        )
        .order_by(Company.rank_score.desc())
        .limit(remaining * 3)  # fetch extra, some may have no contacts
    )
    companies = result.scalars().all()

    sent = 0
    for company in companies:
        if sent >= remaining:
            break

        contacts = await find_linkedin_contacts(
            company_name=company.name,
            domain=company.domain or "",
        )

        for contact in contacts[:2]:  # max 2 contacts per company
            if sent >= remaining:
                break

            note = await compose_linkedin_note(
                contact=contact,
                company_name=company.name,
                company_desc=company.description or "",
            )
            if not note:
                continue

            success = await send_connection_request(contact["linkedin_url"], note)
            if success:
                # Log as outreach
                outreach = OutreachEmail(
                    contact_id=None,
                    subject=f"LinkedIn connection: {contact['name']} @ {company.name}",
                    body=note,
                    sent_at=datetime.now(UTC),
                    channel="linkedin",
                )
                db.add(outreach)
                await db.commit()
                sent += 1
                await asyncio.sleep(3.0)  # Slow down between sends

    logger.info(f"LinkedIn: sent {sent} connection requests today")
    return sent


def _infer_name_from_url(url: str) -> str:
    path = url.rstrip("/").split("/in/")[-1].split("?")[0]
    parts = path.replace("-", " ").split()
    return " ".join(p.capitalize() for p in parts[:2]) if parts else "Unknown"


def _infer_title_from_url_and_text(url: str, title_text: str) -> str:
    title_lower = title_text.lower()
    for t in ["cto", "chief technology", "vp engineering", "head of engineering",
               "co-founder", "founder", "engineering manager", "tech lead"]:
        if t in title_lower:
            return t.title()
    return "Engineering Lead"
