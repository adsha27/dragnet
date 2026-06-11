"""
M2 — Eligibility classifier using local Qwen3 via Ollama.
Handles both Indian market (Delhi/Bangalore) and remote (USD) jobs.
"""

import logging
from dataclasses import dataclass

from dragnet.llm import complete_json

logger = logging.getLogger(__name__)

EOR_PROVIDERS = ["deel", "remote.com", "oyster", "rippling global", "oyster hr", "remote hr"]

# Role keywords that match the candidate's target roles
TARGET_ROLE_KEYWORDS = [
    "backend engineer", "backend developer", "software engineer", "software developer",
    "sde", "sde-1", "sde-2", "sde 1", "sde 2", "swe", "platform engineer",
    "ai engineer", "ml engineer", "machine learning engineer", "ai/ml engineer",
    "llm engineer", "generative ai", "full stack engineer", "fullstack engineer",
    "full-stack engineer", "full stack developer",
]

# Hard reject: managerial/leadership requirements
REJECT_ROLE_KEYWORDS = [
    "vp of engineering", "head of engineering", "director of engineering",
    "engineering manager", "vp engineering",
]

# Salary floors
INDIA_MIN_LPA = 12        # ₹12 LPA minimum
GLOBAL_MIN_USD_MONTH = 1500  # $1,500/month minimum


SYSTEM_PROMPT = """You classify job postings for Aditya — a backend/AI engineer in India (2 years experience) targeting:
- Indian in-office/hybrid roles: ₹12+ LPA, any city (Gurgaon/Delhi/Bangalore/Mumbai/Hyderabad/Pune/Noida/remote)
- Global remote roles: $1,500+/month, must be India-eligible (hired via EOR or global contractor)

TARGET ROLES (pass these through): backend engineer, software engineer, SDE, SWE, platform engineer,
AI engineer, ML engineer, LLM engineer, generative AI engineer, full stack engineer, full stack developer.

HARD REJECT (output eligible=false immediately, no further analysis):
1. Requires 5+ years of experience as a MINIMUM (not preferred) — "minimum 5 years", "5+ years required"
2. Requires managing/leading a team — "people management", "manage engineers", "team lead with direct reports", "hiring manager"
3. Role title is VP, Director, Head of Engineering, Engineering Manager
4. India not eligible for remote role — "US residents only", "must have US work authorization", "US work permit required"
5. India salary clearly stated BELOW ₹12 LPA (e.g., "5-8 LPA")
6. Global salary clearly BELOW $18,000/year ($1,500/month)

ELIGIBILITY SIGNALS:
- "lead" in title is OK if the role is IC (individual contributor), not people management
- "senior" is fine — being senior ≠ managing people
- "5 years preferred" is NOT a hard reject — preferred is softer than required
- Established companies (FAANG, fintech, SaaS, infra) are just as good as startups
- EOR providers (Deel, Remote.com, Oyster, Rippling) = strong India-eligible signal

COMPENSATION EXTRACTION:
- Convert all salaries to monthly USD or LPA. $X/year → /12. ₹X/month → × 12.
- If no salary mentioned: comp_min/max = null, do NOT assume.

Return JSON only, no other text:
{
  "eligible": true | false,
  "reject_reason": null | "overyoe" | "management" | "us_only" | "eu_only" | "comp_too_low" | "wrong_role",
  "market": "remote_global" | "india_office" | "both" | "unknown",
  "remote_scope": "global" | "us_only" | "india_only" | "eu_only" | "unknown",
  "india_eligible": "yes" | "no" | "likely_yes" | "likely_no" | "unknown",
  "comp_min_usd_month": number | null,
  "comp_max_usd_month": number | null,
  "comp_min_lpa": number | null,
  "comp_max_lpa": number | null,
  "city": "delhi" | "bangalore" | "mumbai" | "hyderabad" | "pune" | "noida" | "gurgaon" | "remote" | "other" | null,
  "seniority": "entry" | "mid" | "senior" | "staff" | "lead_ic" | "manager" | "unknown",
  "yoe_min_required": number | null,
  "requires_management": true | false,
  "stack_tags": ["string"],
  "eor_signals": ["string"],
  "reasoning": "one sentence"
}"""


@dataclass
class ClassificationResult:
    eligible: bool
    reject_reason: str | None
    market: str
    remote_scope: str
    india_eligible: str
    comp_min_usd_month: int | None
    comp_max_usd_month: int | None
    comp_min_lpa: int | None
    comp_max_lpa: int | None
    city: str | None
    seniority: str
    yoe_min_required: int | None
    requires_management: bool
    stack_tags: list[str]
    eor_signals: list[str]
    reasoning: str


def pre_filter(title: str, text: str) -> tuple[bool, str | None]:
    """
    Fast string-based pre-filter before LLM classification.
    Returns (eligible, reject_reason). Saves LLM calls on obvious rejects.
    """
    title_lower = title.lower()
    text_lower = (text or "").lower()

    # Role must match target roles
    if not any(kw in title_lower for kw in TARGET_ROLE_KEYWORDS):
        return False, "wrong_role"

    # Hard reject manager/director titles
    if any(kw in title_lower for kw in REJECT_ROLE_KEYWORDS):
        return False, "management"

    # Hard reject US-only signals in text
    us_only_phrases = [
        "must be authorized to work in the us",
        "us work authorization required",
        "must be a us citizen",
        "us persons only",
        "must reside in the united states",
        "us residents only",
    ]
    if any(p in text_lower for p in us_only_phrases):
        return False, "us_only"

    # Hard reject freelance / part-time / hourly / per-project
    freelance_phrases = [
        "freelance", "part-time", "part time", "hourly rate", "per hour",
        "per project", "gig ", "contract-to-hire", "1099", "independent contractor",
        "as-needed basis", "occasional work",
    ]
    if any(p in text_lower for p in freelance_phrases):
        # Allow "contractor" only when paired with EOR signals (full-time contractor via EOR)
        has_eor = any(p in text_lower for p in ["deel", "remote.com", "oyster", "rippling", "employer of record"])
        if not has_eor:
            return False, "freelance"

    return True, None


async def classify_posting(
    company: str,
    title: str,
    text: str,
    posting_id: str = "",
) -> ClassificationResult:
    # Fast pre-filter — skip LLM for obvious rejects
    pre_ok, pre_reason = pre_filter(title, text)
    if not pre_ok:
        return ClassificationResult(
            eligible=False,
            reject_reason=pre_reason,
            market="unknown",
            remote_scope="unknown",
            india_eligible="no",
            comp_min_usd_month=None,
            comp_max_usd_month=None,
            comp_min_lpa=None,
            comp_max_lpa=None,
            city=None,
            seniority="unknown",
            yoe_min_required=None,
            requires_management=False,
            stack_tags=[],
            eor_signals=[],
            reasoning=f"pre_filter: {pre_reason}",
        )

    text_lower = text.lower()
    detected_eor = [p for p in EOR_PROVIDERS if p in text_lower]
    user_content = f"Company: {company}\nTitle: {title}\nPosting:\n{text[:2500]}"

    try:
        data = await complete_json(SYSTEM_PROMPT, user_content, max_tokens=600)
        eor_signals = list(set(data.get("eor_signals", []) + detected_eor))

        eligible = bool(data.get("eligible", False))

        # Enforce comp floors as hard rule even if LLM says eligible
        comp_min_lpa = data.get("comp_min_lpa")
        comp_max_lpa = data.get("comp_max_lpa")
        comp_min_usd_month = data.get("comp_min_usd_month")
        comp_max_usd_month = data.get("comp_max_usd_month")

        reject_reason = data.get("reject_reason")
        if eligible:
            if comp_max_lpa is not None and comp_max_lpa < INDIA_MIN_LPA:
                eligible = False
                reject_reason = "comp_too_low"
            elif comp_max_usd_month is not None and comp_max_usd_month < GLOBAL_MIN_USD_MONTH:
                eligible = False
                reject_reason = "comp_too_low"

        return ClassificationResult(
            eligible=eligible,
            reject_reason=reject_reason,
            market=data.get("market", "unknown"),
            remote_scope=data.get("remote_scope", "unknown"),
            india_eligible=data.get("india_eligible", "unknown"),
            comp_min_usd_month=comp_min_usd_month,
            comp_max_usd_month=comp_max_usd_month,
            comp_min_lpa=comp_min_lpa,
            comp_max_lpa=comp_max_lpa,
            city=data.get("city"),
            seniority=data.get("seniority", "unknown"),
            yoe_min_required=data.get("yoe_min_required"),
            requires_management=bool(data.get("requires_management", False)),
            stack_tags=data.get("stack_tags", []),
            eor_signals=eor_signals,
            reasoning=data.get("reasoning", ""),
        )
    except Exception as e:
        logger.error(f"Classification failed for {company}/{posting_id}: {e}")
        return ClassificationResult(
            eligible=False,
            reject_reason="classification_error",
            market="unknown",
            remote_scope="unknown",
            india_eligible="unknown",
            comp_min_usd_month=None,
            comp_max_usd_month=None,
            comp_min_lpa=None,
            comp_max_lpa=None,
            city=None,
            seniority="unknown",
            yoe_min_required=None,
            requires_management=False,
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
