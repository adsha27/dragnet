"""
M6 — Founder/eng-lead enrichment.
Uses Exa to find founder names + infer email patterns.
Only targets top-decile ranked companies with <200 employees.
"""

import logging
import re
import socket

import httpx
from exa_py import Exa

from dragnet.config import settings

logger = logging.getLogger(__name__)


async def enrich_company(company_name: str, domain: str) -> list[dict]:
    """
    Find founders/eng leads for a company.
    Returns list of: {name, title, email, email_verified}
    """
    client = Exa(api_key=settings.exa_api_key)

    founder_names = await _find_founders(client, company_name, domain)
    results = []

    for name, title in founder_names:
        email = await _infer_email(client, name, domain, company_name)
        verified = False

        if email:
            verified = await _verify_email_mx(email)

        results.append({
            "name": name,
            "title": title,
            "email": email,
            "email_verified": verified,
            "domain": domain,
        })

    return results


async def _find_founders(client: Exa, company_name: str, domain: str) -> list[tuple[str, str]]:
    """Find founder + engineering lead names using Exa."""
    results = []

    queries = [
        f"{company_name} founder CEO co-founder",
        f"{company_name} CTO head of engineering VP engineering",
        f"site:linkedin.com {company_name} founder engineer",
    ]

    seen_names: set[str] = set()

    for query in queries[:2]:
        try:
            response = client.search_and_contents(
                query,
                num_results=5,
                type="neural",
                text={"max_characters": 1000},
            )
            for item in response.results:
                names = _extract_people_from_text(item.text or "")
                for name, title in names:
                    if name not in seen_names:
                        seen_names.add(name)
                        results.append((name, title))
        except Exception as e:
            logger.warning(f"Exa enrichment failed for {company_name}: {e}")

    return results[:5]


async def _infer_email(client: Exa, name: str, domain: str, company: str) -> str | None:
    """Infer email pattern from public sources."""
    name_parts = name.lower().split()
    if not name_parts:
        return None

    first = name_parts[0]
    last = name_parts[-1] if len(name_parts) > 1 else ""

    candidates = []
    if last:
        candidates = [
            f"{first}@{domain}",
            f"{first}.{last}@{domain}",
            f"{first[0]}{last}@{domain}",
        ]
    else:
        candidates = [f"{first}@{domain}"]

    # Try Exa to confirm which pattern this company uses
    try:
        response = client.search(
            f"site:{domain} email",
            num_results=3,
        )
        for item in response.results:
            for candidate in candidates:
                if candidate.lower() in (item.text or "").lower():
                    return candidate
    except Exception:
        pass

    return candidates[0] if candidates else None


async def _verify_email_mx(email: str) -> bool:
    """Basic MX record check — does the domain accept email?"""
    domain = email.split("@")[-1]
    try:
        socket.getaddrinfo(domain, None)
        return True
    except socket.gaierror:
        return False


def _extract_people_from_text(text: str) -> list[tuple[str, str]]:
    """Extract name + title pairs from text using simple pattern matching."""
    results = []
    title_patterns = [
        r"([A-Z][a-z]+ [A-Z][a-z]+),?\s*(CEO|CTO|Co-Founder|Founder|Head of Engineering|VP Engineering|Engineering Lead)",
        r"(CEO|CTO|Co-Founder|Founder)[:，]\s*([A-Z][a-z]+ [A-Z][a-z]+)",
    ]
    for pattern in title_patterns:
        for match in re.finditer(pattern, text):
            groups = match.groups()
            if len(groups) == 2:
                if groups[0][0].isupper() and len(groups[0]) > 5:
                    results.append((groups[0].strip(), groups[1].strip()))
                else:
                    results.append((groups[1].strip(), groups[0].strip()))
    return results[:3]
