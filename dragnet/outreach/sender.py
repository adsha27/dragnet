"""
M6 — Founder outreach email sender.
3-line email format: what you built on their stack, link, one production metric.
Rate limited: ≤15/day (deliverability constraint, not courtesy).
Sent via Gmail API from your own address.
"""

import base64
import logging
from datetime import date, datetime, timezone
UTC = timezone.utc
from email.mime.text import MIMEText

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.config import settings
from dragnet.llm import complete
from dragnet.db.models import Company, FounderContact, OutreachEmail
from dragnet.tailoring.facts import facts_as_context_string

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write cold outreach emails for a job candidate.

Format: exactly 3 lines, no greeting, no signature line (added separately).
Line 1: What you built that is directly relevant to their company's stack or category. Be specific.
Line 2: A link or proof point. Use the GitHub link or a specific production metric from the fact sheet only.
Line 3: One direct ask - a 20-minute call or to see if there is a fit.

Rules:
- No filler. No "I'm excited about", "I would love to", "I came across your company".
- Line 1 must reference something specific about THEIR product or stack.
- Use only facts from the provided fact sheet.
- Under 100 words total.
- No em-dashes. Use plain dashes or commas.
- Write like a person, not a cover letter."""


async def emails_sent_today(db: AsyncSession) -> int:
    today = date.today()
    result = await db.execute(
        select(func.count()).select_from(OutreachEmail).where(
            func.date(OutreachEmail.sent_at) == today,
            OutreachEmail.sent_at.is_not(None),
        )
    )
    return result.scalar() or 0


async def compose_outreach(contact: FounderContact, company: Company) -> str:
    """Compose a 3-line cold email using local Qwen."""
    facts_context = facts_as_context_string()

    prompt = f"""TARGET:
Name: {contact.name}
Title: {contact.title or 'Founder/Engineering Lead'}
Company: {company.name}
Company context: {company.description or 'No additional context'}

CANDIDATE FACTS:
{facts_context}

Write the 3-line cold email now."""

    response = await complete(SYSTEM_PROMPT, prompt, max_tokens=200)
    return response.content


async def send_outreach(
    contact: FounderContact,
    company: Company,
    db: AsyncSession,
) -> bool:
    """
    Compose and send a cold outreach email.
    Returns True if sent, False if rate-limited or error.
    """
    today_count = await emails_sent_today(db)
    if today_count >= settings.max_founder_emails_per_day:
        logger.info(f"Daily founder email limit ({settings.max_founder_emails_per_day}) reached")
        return False

    if not contact.email or not contact.email_verified:
        logger.warning(f"No verified email for {contact.name} at {company.name}")
        return False

    body = await compose_outreach(contact, company)
    subject = f"Quick note — backend/AI engineer"

    signature = f"\n\n—\n{settings.applicant_name}\n{settings.applicant_github}\n{settings.applicant_email}"
    full_body = body + signature

    try:
        _send_via_gmail(contact.email, subject, full_body)
    except Exception as e:
        logger.error(f"Failed to send email to {contact.email}: {e}")
        return False

    outreach = OutreachEmail(
        contact_id=contact.id,
        subject=subject,
        body=full_body,
        sent_at=datetime.now(UTC),
    )
    db.add(outreach)
    await db.commit()

    logger.info(f"Sent outreach to {contact.name} <{contact.email}> at {company.name}")
    return True


def _send_via_gmail(to: str, subject: str, body: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(settings.gmail_token_file))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build("gmail", "v1", credentials=creds)

    msg = MIMEText(body)
    msg["to"] = to
    msg["from"] = settings.gmail_sender_address
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
