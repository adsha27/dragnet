"""
M5 — Gmail reply ingestion.
Reads inbox for recruiter replies and advances application states.
Uses Gmail API with label-based filtering.
"""

import base64
import logging
import re
from datetime import datetime, timezone
UTC = timezone.utc

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.config import settings
from dragnet.db.models import Application, ApplicationState
from dragnet.crm.state import transition

logger = logging.getLogger(__name__)

REJECTION_PHRASES = [
    "not moving forward", "decided to move forward with other candidates",
    "won't be moving forward", "not a match", "decided not to proceed",
    "after careful consideration", "we have decided", "unsuccessful",
    "not selected", "position has been filled",
]

POSITIVE_PHRASES = [
    "schedule a call", "would love to chat", "interested in speaking",
    "next steps", "phone screen", "video interview", "technical interview",
    "let's connect", "like to learn more", "advance you",
]


def _get_gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = None
    token_path = settings.gmail_token_file

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path))

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "Gmail credentials not configured. Run: dragnet gmail-auth"
            )

    return build("gmail", "v1", credentials=creds)


async def ingest_replies(db: AsyncSession) -> int:
    """
    Check Gmail for recruiter replies and advance application states.
    Returns number of state changes made.
    """
    try:
        service = _get_gmail_service()
    except RuntimeError as e:
        logger.warning(f"Gmail not configured: {e}")
        return 0

    # Fetch unread messages not from yourself
    try:
        response = service.users().messages().list(
            userId="me",
            q=f"is:unread -from:{settings.applicant_email}",
            maxResults=50,
        ).execute()
    except Exception as e:
        logger.error(f"Gmail API error: {e}")
        return 0

    messages = response.get("messages", [])
    changes = 0

    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="full",
            ).execute()

            sender = _get_header(msg, "From")
            subject = _get_header(msg, "Subject")
            body = _get_body(msg)

            company_name = _extract_company_from_sender(sender)
            if not company_name:
                continue

            app = await _find_application_by_company(db, company_name)
            if not app or app.state not in (ApplicationState.submitted, ApplicationState.screened):
                continue

            if _is_positive(subject, body):
                await transition(app, ApplicationState.screened, f"gmail_reply:{sender}", db)
                changes += 1
                logger.info(f"Advanced {company_name} to SCREENED based on email from {sender}")
            elif _is_rejection(subject, body):
                await transition(app, ApplicationState.rejected, f"gmail_rejection:{sender}", db)
                changes += 1
                logger.info(f"Advanced {company_name} to REJECTED based on email from {sender}")

        except Exception as e:
            logger.error(f"Error processing message {msg_ref['id']}: {e}")

    await db.commit()
    return changes


def _get_header(msg: dict, name: str) -> str:
    headers = msg.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _get_body(msg: dict) -> str:
    try:
        parts = msg.get("payload", {}).get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        data = msg.get("payload", {}).get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _is_positive(subject: str, body: str) -> bool:
    text = (subject + " " + body).lower()
    return any(phrase in text for phrase in POSITIVE_PHRASES)


def _is_rejection(subject: str, body: str) -> bool:
    text = (subject + " " + body).lower()
    return any(phrase in text for phrase in REJECTION_PHRASES)


def _extract_company_from_sender(sender: str) -> str | None:
    """Extract company domain from sender email."""
    match = re.search(r'@([\w.-]+)', sender)
    if not match:
        return None
    domain = match.group(1).lower()
    # Strip common email domains
    if domain in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com"):
        return None
    parts = domain.split(".")
    return parts[-2] if len(parts) >= 2 else None


async def _find_application_by_company(db: AsyncSession, company_name_fragment: str) -> Application | None:
    result = await db.execute(select(Application))
    apps = result.scalars().all()
    for app in apps:
        if app.posting and app.posting.company:
            if company_name_fragment.lower() in app.posting.company.name.lower():
                return app
    return None
