"""
Recruitee public job board crawler.
Endpoint: https://{slug}.recruitee.com/api/offers/
No auth required. Public API via company subdomain.
Apply URL: https://{slug}.recruitee.com/o/{offer-slug}
"""

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_postings(slug: str, company_name: str) -> list[dict]:
    url = f"https://{slug}.recruitee.com/api/offers/"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            if response.status_code == 404:
                logger.warning(f"Recruitee: no board for slug={slug}")
                return []
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as e:
        logger.error(f"Recruitee fetch failed for {slug}: {e}")
        return []

    offers = data.get("offers", [])
    return [_normalize(o, slug, company_name) for o in offers]


def _normalize(offer: dict, slug: str, company_name: str) -> dict:
    location = offer.get("city") or offer.get("country") or ""
    if offer.get("remote"):
        location = f"Remote, {location}".strip(", ")

    apply_url = offer.get("careers_url") or f"https://{slug}.recruitee.com/o/{offer.get('slug', '')}"

    content_parts = [
        offer.get("description", ""),
        offer.get("requirements", ""),
        offer.get("offer", ""),
    ]
    content_text = " ".join(p for p in content_parts if p).strip()

    return {
        "external_id": str(offer.get("id", "")),
        "company_name": company_name,
        "company_slug": slug,
        "ats_type": "recruitee",
        "title": offer.get("title", ""),
        "location": location,
        "apply_url": apply_url,
        "content_text": content_text,
        "raw_json": offer,
        "dedup_hash": _dedup_hash(company_name, offer.get("title", ""), location),
    }


def _dedup_hash(company: str, title: str, location: str) -> str:
    key = f"{company.lower()}|{title.lower()}|{location.lower()}"
    return hashlib.sha256(key.encode()).hexdigest()
