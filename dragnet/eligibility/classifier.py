"""
M2 — Eligibility classifier using local Qwen3 via Ollama.
Handles both Indian market (Delhi/Bangalore) and remote (USD) jobs.

Batch mode: classify up to BATCH_SIZE jobs per LLM call for 3-4x throughput.
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

# Hard reject by title — non-tech roles that sometimes contain tech keywords
REJECT_ROLE_KEYWORDS = [
    # Leadership
    "vp of engineering", "head of engineering", "director of engineering",
    "engineering manager", "vp engineering", "chief of staff",
    # Sales & GTM
    "account executive", "account manager", "sales engineer", "solutions engineer",
    "sales development", "business development", "revenue operations",
    "customer success", "customer support", "technical support", "support engineer",
    "solutions architect", "field engineer", "pre-sales",
    # Marketing
    "marketing", "content strategist", "growth engineer", "seo",
    # Design & Product
    "product manager", "product designer", "ux designer", "ui designer",
    "visual designer", "brand designer", "creative director",
    # Data & Analytics (not engineering)
    "data analyst", "data scientist", "analytics engineer", "business analyst",
    "business intelligence", "bi engineer",
    # Ops & Finance & Legal
    "recruiter", "talent acquisition", "people operations", "hr ", "human resources",
    "finance", "accounting", "legal counsel", "paralegal", "compliance",
    "operations manager", "program manager", "project manager",
    # Hardware / non-software
    "hardware engineer", "electrical engineer", "mechanical engineer",
    "firmware engineer", "fpga",
]

# Salary floors
INDIA_MIN_LPA = 12        # ₹12 LPA minimum
GLOBAL_MIN_USD_MONTH = 1500  # $1,500/month minimum


SYSTEM_PROMPT = """Classify job postings. Candidate: backend/AI engineer in India, 2 YoE.
TARGETS: Indian roles ₹12+LPA | Global remote $1500+/mo India-eligible.
ROLES: backend/software/platform/AI/ML/LLM/fullstack engineer, SDE, SWE.
REJECT: 5+ YoE MINIMUM required | people management | VP/Director/EM titles | US-only remote | comp clearly below floors.
OK: "senior", "lead" IC, "5 yrs preferred", EOR providers (Deel/Remote.com/Oyster/Rippling).
Salary: convert to monthly USD or LPA. $X/yr÷12. If absent: null.
EOR signals = India-eligible for remote.

Return JSON array, one object per job, same order as input:
[{"idx":0,"eligible":bool,"reject_reason":null|"overyoe"|"management"|"us_only"|"comp_too_low"|"wrong_role","market":"remote_global"|"india_office"|"both"|"unknown","india_eligible":"yes"|"no"|"likely_yes"|"unknown","comp_min_usd_month":num|null,"comp_max_usd_month":num|null,"comp_min_lpa":num|null,"comp_max_lpa":num|null,"city":"delhi"|"bangalore"|"mumbai"|"hyderabad"|"pune"|"noida"|"gurgaon"|"remote"|"other"|null,"seniority":"entry"|"mid"|"senior"|"staff"|"lead_ic"|"manager"|"unknown","yoe_min_required":num|null,"requires_management":bool,"stack_tags":["str"],"eor_signals":["str"],"reasoning":"one sentence"}]"""

BATCH_SIZE = 5  # jobs per LLM call — qwen3:14b handles 5 × 800 chars easily


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
    user_content = f"[{{\"idx\":0,\"company\":\"{company}\",\"title\":\"{title}\",\"text\":{repr(text[:800])}}}]"

    try:
        raw = await complete_json(SYSTEM_PROMPT, user_content, max_tokens=400)
        # Single-job call returns array with one item
        data = raw[0] if isinstance(raw, list) else raw
        return _result_from_data(data, detected_eor)
    except Exception as e:
        logger.error(f"Classification failed for {company}/{posting_id}: {e}")
        return ClassificationResult(
            eligible=False, reject_reason="classification_error",
            market="unknown", remote_scope="unknown", india_eligible="unknown",
            comp_min_usd_month=None, comp_max_usd_month=None,
            comp_min_lpa=None, comp_max_lpa=None, city=None,
            seniority="unknown", yoe_min_required=None, requires_management=False,
            stack_tags=[], eor_signals=detected_eor,
            reasoning=f"classification_error: {e}",
        )


def _result_from_data(data: dict, detected_eor: list[str]) -> ClassificationResult:
    eor_signals = list(set(data.get("eor_signals", []) + detected_eor))
    eligible = bool(data.get("eligible", False))
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


async def classify_jobs_batch(jobs: list[dict]) -> list[ClassificationResult]:
    """
    Classify BATCH_SIZE jobs in a single LLM call.
    Falls back to error result per job if LLM fails.
    """
    # Build user message: JSON array of {idx, company, title, text}
    items = []
    eor_per_job: list[list[str]] = []
    for i, j in enumerate(jobs):
        text = j.get("content_text", "")
        eor_per_job.append([p for p in EOR_PROVIDERS if p in text.lower()])
        items.append({
            "idx": i,
            "company": j.get("company_name", ""),
            "title": j.get("title", ""),
            "text": text[:800],
        })

    import json as _json
    user_content = _json.dumps(items, ensure_ascii=False)

    error_result = lambda i, e: ClassificationResult(
        eligible=False, reject_reason="classification_error",
        market="unknown", remote_scope="unknown", india_eligible="unknown",
        comp_min_usd_month=None, comp_max_usd_month=None,
        comp_min_lpa=None, comp_max_lpa=None, city=None,
        seniority="unknown", yoe_min_required=None, requires_management=False,
        stack_tags=[], eor_signals=eor_per_job[i],
        reasoning=f"classification_error: {e}",
    )

    try:
        raw = await complete_json(SYSTEM_PROMPT, user_content, max_tokens=BATCH_SIZE * 400)
        if not isinstance(raw, list):
            raw = [raw]
        # Sort by idx to guarantee order, pad missing with errors
        by_idx = {item.get("idx", i): item for i, item in enumerate(raw)}
        results = []
        for i in range(len(jobs)):
            if i in by_idx:
                try:
                    results.append(_result_from_data(by_idx[i], eor_per_job[i]))
                except Exception as e:
                    results.append(error_result(i, e))
            else:
                results.append(error_result(i, "missing from LLM response"))
        return results
    except Exception as e:
        logger.error(f"Batch classification failed: {e}")
        return [error_result(i, e) for i in range(len(jobs))]
