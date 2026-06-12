"""
Import eligible jobs from output/eligible_jobs.json into the Postgres DB.
Safe to re-run — skips existing dedup_hash records.

Usage:
    python scripts/import_eligible_jobs.py
    python scripts/import_eligible_jobs.py --input output/eligible_jobs.json
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from dragnet.db.connection import SessionLocal, init_db
from dragnet.db.models import Application, ApplicationState, ATSType, Company, Posting, Seniority
from dragnet.tailoring.categories import categorize_job

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _detect_ats(url: str) -> ATSType:
    if not url:
        return ATSType.unknown
    u = url.lower()
    if "greenhouse.io" in u or "boards.greenhouse" in u:
        return ATSType.greenhouse
    if "lever.co" in u:
        return ATSType.lever
    if "ashby" in u or "jobs.ashbyhq" in u:
        return ATSType.ashby
    if "linkedin.com" in u:
        return ATSType.linkedin
    if "naukri.com" in u:
        return ATSType.naukri
    return ATSType.unknown


def _normalize_unicode(text: str) -> str:
    """ATS-safe: replace fancy punctuation with ASCII equivalents."""
    if not text:
        return text
    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "–": "-",   # en-dash
        "—": "-",   # em-dash
        "‘": "'",   # left single quote
        "’": "'",   # right single quote
        "“": '"',   # left double quote
        "”": '"',   # right double quote
        "•": "-",   # bullet
        "…": "...", # ellipsis
        " ": " ",   # non-breaking space
        "​": "",    # zero-width space
        "‌": "",    # zero-width non-joiner
        "‍": "",    # zero-width joiner
        "﻿": "",    # BOM
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _company_slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:100]


def _seniority_from_classification(data: dict) -> Seniority:
    raw = (data.get("seniority") or "").lower()
    mapping = {
        "entry": Seniority.entry,
        "mid": Seniority.mid,
        "senior": Seniority.senior,
        "staff": Seniority.staff,
        "lead": Seniority.lead,
        "manager": Seniority.manager,
    }
    return mapping.get(raw, Seniority.unknown)


async def import_jobs(jobs_path: Path) -> tuple[int, int, int]:
    """Returns (inserted, skipped, errored)."""
    raw = json.loads(jobs_path.read_text())
    logger.info(f"Loading {len(raw)} eligible jobs from {jobs_path}")

    await init_db()

    inserted = skipped = errored = 0

    async with SessionLocal() as session:
        for job in raw:
            try:
                dedup_hash = job.get("dedup_hash") or ""
                if not dedup_hash:
                    errored += 1
                    continue

                # Skip if already imported
                existing = await session.scalar(
                    select(Posting).where(Posting.dedup_hash == dedup_hash)
                )
                if existing:
                    skipped += 1
                    continue

                company_name = _normalize_unicode(
                    job.get("company_name") or job.get("company") or "Unknown"
                )
                company_slug = _company_slug(company_name)
                apply_url = job.get("apply_url") or ""
                ats_type = _detect_ats(apply_url)

                # Upsert company
                stmt = insert(Company).values(
                    name=company_name,
                    slug=company_slug,
                    ats_type=ats_type,
                ).on_conflict_do_nothing(constraint="uq_company_slug_ats")
                await session.execute(stmt)
                await session.flush()

                company = await session.scalar(
                    select(Company).where(
                        Company.slug == company_slug,
                        Company.ats_type == ats_type,
                    )
                )
                if not company:
                    errored += 1
                    continue

                classification = job.get("_classification", {})
                category = categorize_job(job)

                raw_json = job.get("raw_json") or {}
                raw_json["category"] = category

                posting = Posting(
                    company_id=company.id,
                    external_id=str(job.get("external_id") or dedup_hash[:20]),
                    title=_normalize_unicode(job.get("title") or "Unknown"),
                    location=_normalize_unicode(job.get("location") or ""),
                    apply_url=apply_url,
                    raw_json=raw_json,
                    content_text=_normalize_unicode(job.get("content_text") or ""),
                    dedup_hash=dedup_hash,
                    seniority=_seniority_from_classification(classification),
                    stack_tags=classification.get("stack_tags"),
                    eor_signals=classification.get("eor_signals"),
                )
                session.add(posting)
                await session.flush()

                application = Application(
                    posting_id=posting.id,
                    state=ApplicationState.eligible,
                )
                session.add(application)
                inserted += 1

            except Exception as e:
                logger.warning(f"Error importing job {job.get('external_id','?')}: {e}")
                errored += 1
                await session.rollback()
                continue

        await session.commit()

    return inserted, skipped, errored


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="output/eligible_jobs.json")
    args = parser.parse_args()

    jobs_path = Path(args.input)
    if not jobs_path.exists():
        logger.error(f"File not found: {jobs_path}")
        logger.info("Run eligibility filter first: python scripts/run_eligibility.py")
        sys.exit(1)

    inserted, skipped, errored = await import_jobs(jobs_path)
    print(f"\nImport complete: {inserted} inserted, {skipped} skipped (already exist), {errored} errors")


if __name__ == "__main__":
    asyncio.run(main())
