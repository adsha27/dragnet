"""
M2 — Eligibility classifier using local Qwen3 via Ollama.
Handles both Indian market (Delhi/Bangalore) and remote (USD) jobs.
"""

import logging
from dataclasses import dataclass

from dragnet.llm import complete_json

logger = logging.getLogger(__name__)

EOR_PROVIDERS = ["deel", "remote.com", "oyster", "rippling global", "oyster hr", "remote hr"]

SYSTEM_PROMPT = """You classify job postings for a backend engineer in India looking for remote or Indian in-office roles.

Markets to classify:
1. US/global remote: can apply from India, paid in USD
2. Indian office: Delhi or Bangalore, paid in INR
3. Both possible (remote-friendly Indian company)

For remote/global jobs - key signals:
- Deel, Remote.com, Oyster, Rippling Global mentions = strong yes
- "US only", "must be US resident", "US work authorization required" = hard no
- "remote" without restriction at a small startup = likely yes
- APAC, Asia, India, worldwide, "any country" mentions = yes

For Indian jobs:
- Extract salary in LPA (lakhs per annum) if mentioned
- Extract city: delhi, bangalore, mumbai, remote, hybrid
- "work from office" with city = indian_market posting

Return JSON only, no other text:
{
  "market": "remote_global" | "india_office" | "both" | "unknown",
  "remote_scope": "global" | "us_only" | "india_only" | "eu_only" | "unknown",
  "india_eligible": "yes" | "no" | "likely_yes" | "likely_no" | "unknown",
  "comp_min_usd": number | null,
  "comp_max_usd": number | null,
  "comp_min_lpa": number | null,
  "comp_max_lpa": number | null,
  "city": "delhi" | "bangalore" | "mumbai" | "remote" | "other" | null,
  "seniority": "entry" | "mid" | "senior" | "staff" | "lead" | "manager" | "unknown",
  "stack_tags": ["string"],
  "eor_signals": ["string"],
  "reasoning": "one sentence"
}"""


@dataclass
class ClassificationResult:
    market: str
    remote_scope: str
    india_eligible: str
    comp_min_usd: int | None
    comp_max_usd: int | None
    comp_min_lpa: int | None
    comp_max_lpa: int | None
    city: str | None
    seniority: str
    stack_tags: list[str]
    eor_signals: list[str]
    reasoning: str


async def classify_posting(
    company: str,
    title: str,
    text: str,
    posting_id: str = "",
) -> ClassificationResult:
    text_lower = text.lower()
    detected_eor = [p for p in EOR_PROVIDERS if p in text_lower]

    user_content = f"Company: {company}\nTitle: {title}\nPosting:\n{text[:2500]}"

    try:
        data = await complete_json(SYSTEM_PROMPT, user_content, max_tokens=512)
        eor_signals = list(set(data.get("eor_signals", []) + detected_eor))

        return ClassificationResult(
            market=data.get("market", "unknown"),
            remote_scope=data.get("remote_scope", "unknown"),
            india_eligible=data.get("india_eligible", "unknown"),
            comp_min_usd=data.get("comp_min_usd"),
            comp_max_usd=data.get("comp_max_usd"),
            comp_min_lpa=data.get("comp_min_lpa"),
            comp_max_lpa=data.get("comp_max_lpa"),
            city=data.get("city"),
            seniority=data.get("seniority", "unknown"),
            stack_tags=data.get("stack_tags", []),
            eor_signals=eor_signals,
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        logger.error(f"Classification failed for {company}/{posting_id}: {e}")
        return ClassificationResult(
            market="unknown",
            remote_scope="unknown",
            india_eligible="unknown",
            comp_min_usd=None,
            comp_max_usd=None,
            comp_min_lpa=None,
            comp_max_lpa=None,
            city=None,
            seniority="unknown",
            stack_tags=[],
            eor_signals=detected_eor,
            reasoning=f"classification_error: {e}",
        )


async def classify_batch(postings: list[dict]) -> list[ClassificationResult]:
    results = []
    for p in postings:
        result = await classify_posting(
            company=p.get("company_name", ""),
            title=p.get("title", ""),
            text=p.get("content_text", ""),
            posting_id=str(p.get("id", "")),
        )
        results.append(result)
    return results
