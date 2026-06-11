"""
M2 — Ranking formula.
Handles both remote-USD and Indian-INR jobs.

Thresholds:
- Remote: india_eligible + comp >= $2000/month ($24k/year USD)
- Delhi: india_office + comp >= 12 LPA
- Bangalore: india_office + comp >= 15 LPA
- india_eligible == "no" AND market == "remote_global" -> score = 0
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.db.models import Posting
from dragnet.eligibility.classifier import ClassificationResult, classify_posting

ADITYA_STACK = {
    "go", "python", "sql", "fastapi", "postgresql", "pgvector", "mongodb",
    "llm", "rag", "mcp", "agents", "observability", "docker", "aws",
    "whatsapp", "backend", "api", "rest", "websocket", "grpc",
}

DELHI_LPA_MIN = 12
BANGALORE_LPA_MIN = 15
REMOTE_USD_ANNUAL_MIN = 24_000  # $2000/month


def score_posting(c: ClassificationResult) -> float:
    """
    Returns 0 for hard-filtered postings. Higher = apply sooner.
    """
    # Hard gates
    if c.market == "remote_global" and c.india_eligible == "no":
        return 0.0
    if c.market == "india_office":
        return _score_indian(c)

    return _score_remote(c)


def _score_remote(c: ClassificationResult) -> float:
    score = 0.0

    eligibility_scores = {"yes": 10.0, "likely_yes": 6.0, "unknown": 2.0, "likely_no": 0.0, "no": 0.0}
    score += eligibility_scores.get(c.india_eligible, 0.0)

    if c.comp_min_usd:
        annual = c.comp_min_usd
        if annual >= 60_000:
            score += 8.0
        elif annual >= REMOTE_USD_ANNUAL_MIN:
            score += 5.0
        else:
            return 0.0  # below $2k/month threshold

    if c.eor_signals:
        score += 3.0

    score += _stack_overlap(c)

    if c.seniority in ("entry", "mid", "unknown"):
        score += 2.0

    return score


def _score_indian(c: ClassificationResult) -> float:
    score = 0.0
    city = (c.city or "").lower()

    if city == "delhi":
        threshold = DELHI_LPA_MIN
        score += 8.0
    elif city == "bangalore":
        threshold = BANGALORE_LPA_MIN
        score += 7.0
    elif city == "remote":
        threshold = 10.0
        score += 6.0
    else:
        threshold = 10.0
        score += 3.0

    if c.comp_min_lpa is not None and c.comp_min_lpa < threshold:
        return 0.0

    if c.comp_min_lpa is not None:
        score += min((c.comp_min_lpa - threshold) * 0.5, 5.0)

    score += _stack_overlap(c)

    if c.seniority in ("entry", "mid", "unknown"):
        score += 2.0

    return score


def _stack_overlap(c: ClassificationResult) -> float:
    if not c.stack_tags:
        return 0.0
    tags_lower = {t.lower() for t in c.stack_tags}
    return min(len(tags_lower & ADITYA_STACK) * 1.0, 5.0)


async def classify_and_rank_pending(session: AsyncSession) -> int:
    result = await session.execute(
        select(Posting).where(Posting.classified_at.is_(None)).limit(200)
    )
    postings = result.scalars().all()

    count = 0
    for posting in postings:
        company_name = posting.company.name if posting.company else "Unknown"
        c = await classify_posting(
            company=company_name,
            title=posting.title,
            text=posting.content_text or "",
            posting_id=str(posting.id),
        )

        posting.remote_scope = c.remote_scope
        posting.india_eligible = c.india_eligible
        posting.comp_min = c.comp_min_usd
        posting.comp_max = c.comp_max_usd
        posting.seniority = c.seniority
        posting.stack_tags = c.stack_tags
        posting.eor_signals = c.eor_signals
        posting.stack_match_score = _stack_overlap(c)
        posting.rank_score = score_posting(c)
        posting.classified_at = datetime.utcnow()
        count += 1

    await session.commit()
    return count
