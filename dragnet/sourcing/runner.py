"""
Sourcing orchestrator: crawl ATS APIs + Naukri + LinkedIn, dedup, persist.
"""

import logging
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.db.models import ATSType, Company, Posting
from dragnet.sourcing.ats import ashby, greenhouse, lever
from dragnet.sourcing import naukri, linkedin

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).parent.parent.parent / "slugs" / "seed.yaml"

# Synthetic slugs for non-ATS sources — used as the Company.slug in DB
NAUKRI_SLUG = "_naukri_search"
LINKEDIN_SLUG = "_linkedin_search"


async def run_sourcing(session: AsyncSession) -> dict[str, int]:
    """Run full sourcing pass. Returns counts by source."""
    counts: dict[str, int] = {
        "greenhouse": 0, "lever": 0, "ashby": 0,
        "naukri": 0, "linkedin": 0, "total_new": 0,
    }

    # ── ATS sources (seed.yaml) ──────────────────────────────────────
    seed = yaml.safe_load(SEED_FILE.read_text())
    for ats_type, entries in seed.items():
        if not entries or ats_type not in ("greenhouse", "lever", "ashby"):
            continue
        for entry in entries:
            company = await _get_or_create_company(
                session, entry["company"], entry["slug"], ats_type
            )
            postings = await _fetch_for_ats(ats_type, entry["slug"], entry["company"])
            new = await _persist_postings(session, company, postings)
            counts[ats_type] += new
            counts["total_new"] += new
            if new:
                logger.info(f"{entry['company']} ({ats_type}): {new} new postings")

    # ── Naukri ───────────────────────────────────────────────────────
    logger.info("Starting Naukri sourcing pass...")
    naukri_company = await _get_or_create_company(
        session, "Naukri Search", NAUKRI_SLUG, "naukri"
    )
    naukri_postings = await naukri.fetch_postings()
    for p in naukri_postings:
        # Each posting has its own company_name — create/find that company
        company = await _get_or_create_named_company(session, p["company_name"], "naukri")
        new = await _persist_postings(session, company, [p])
        counts["naukri"] += new
        counts["total_new"] += new

    # ── LinkedIn ─────────────────────────────────────────────────────
    logger.info("Starting LinkedIn sourcing pass...")
    li_postings = await linkedin.fetch_postings()
    for p in li_postings:
        company = await _get_or_create_named_company(session, p["company_name"], "linkedin")
        new = await _persist_postings(session, company, [p])
        counts["linkedin"] += new
        counts["total_new"] += new

    await session.commit()
    logger.info(f"Sourcing complete: {counts}")
    return counts


async def _fetch_for_ats(ats_type: str, slug: str, company_name: str) -> list[dict]:
    if ats_type == "greenhouse":
        return await greenhouse.fetch_postings(slug, company_name)
    elif ats_type == "lever":
        return await lever.fetch_postings(slug, company_name)
    elif ats_type == "ashby":
        return await ashby.fetch_postings(slug, company_name)
    return []


async def _get_or_create_company(
    session: AsyncSession, name: str, slug: str, ats_type_str: str
) -> Company:
    ats = ATSType(ats_type_str)
    result = await session.execute(
        select(Company).where(Company.slug == slug, Company.ats_type == ats)
    )
    company = result.scalar_one_or_none()
    if company is None:
        company = Company(name=name, slug=slug, ats_type=ats)
        session.add(company)
        await session.flush()
    return company


async def _get_or_create_named_company(
    session: AsyncSession, name: str, ats_type_str: str
) -> Company:
    """For Naukri/LinkedIn where the slug is derived from the company name."""
    slug = name.lower().replace(" ", "-").replace(".", "")[:80] + f"-{ats_type_str}"
    return await _get_or_create_company(session, name, slug, ats_type_str)


async def _persist_postings(session: AsyncSession, company: Company, postings: list[dict]) -> int:
    new_count = 0
    for p in postings:
        result = await session.execute(
            select(Posting).where(Posting.dedup_hash == p["dedup_hash"])
        )
        if result.scalar_one_or_none() is not None:
            continue

        posting = Posting(
            company_id=company.id,
            external_id=p["external_id"],
            title=p["title"],
            location=p.get("location", ""),
            apply_url=p["apply_url"],
            raw_json=p["raw_json"],
            content_text=p.get("content_text", ""),
            dedup_hash=p["dedup_hash"],
        )
        session.add(posting)
        new_count += 1

    return new_count
