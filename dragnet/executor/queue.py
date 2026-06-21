"""
M4 — Application queue + human approval gate.
First 50 submissions: require explicit human approval.
After 50: 10% sampling (approve 1 in 10).
CAPTCHA / login-wall failures → human queue (not retried automatically).
"""

import logging
import random
from datetime import datetime, timezone

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.config import settings
from dragnet.db.models import Application, ApplicationState, FailureType, Posting, StateTransition
from dragnet.eligibility.liveness import check_liveness
from dragnet.eligibility.ranker import classify_and_rank_pending
from dragnet.executor import session as browser_session
from dragnet.executor.adapters import greenhouse, lever, linkedin as linkedin_adapter
from dragnet.tailoring.answers import generate_answers

logger = logging.getLogger(__name__)


async def get_submitted_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(Application).where(
            Application.state.in_([
                ApplicationState.submitted,
                ApplicationState.screened,
                ApplicationState.interviewing,
                ApplicationState.offer,
            ])
        )
    )
    return result.scalar() or 0


def needs_human_approval(submitted_count: int) -> bool:
    if submitted_count < settings.approval_gate_count:
        return True
    return random.random() < settings.approval_sample_rate


_CATEGORY_RESUMES_DIR = Path("output/category_resumes")


async def run_tailoring_pass(db: AsyncSession, limit: int = 50) -> int:
    """
    Assign pre-reviewed category resumes to eligible postings.
    No LLM calls — just resolves output/category_resumes/<category>.pdf.
    Returns count of postings advanced to tailored state.
    """
    result = await db.execute(
        select(Posting, Application)
        .join(Application, Posting.id == Application.posting_id)
        .where(Application.state == ApplicationState.eligible)
        .options(selectinload(Application.posting).selectinload(Posting.company))
        .limit(limit)
    )

    count = 0
    for posting, application in result.all():
        apply_url = posting.apply_url or ""

        # LinkedIn: mark as tailored so executor handles it via linkedin_adapter
        if "linkedin.com" in apply_url:
            category = (posting.raw_json or {}).get("category", "india_backend")
            pdf_path = _CATEGORY_RESUMES_DIR / f"{category}.pdf"
            if pdf_path.exists():
                application.state = ApplicationState.tailored
                application.resume_path = str(pdf_path)
                await _record_transition(db, application, ApplicationState.tailored, "tailoring_pass")
                count += 1
            await db.commit()
            continue

        # Liveness check for direct ATS URLs
        liveness = await check_liveness(apply_url)
        if not liveness.live:
            logger.warning(f"Dead posting {posting.id} ({liveness.reason}): {apply_url}")
            application.state = ApplicationState.ineligible
            await _record_transition(db, application, ApplicationState.ineligible, "liveness_check")
            await db.commit()
            continue

        # Resolve category PDF
        category = (posting.raw_json or {}).get("category", "india_backend")
        pdf_path = _CATEGORY_RESUMES_DIR / f"{category}.pdf"
        if not pdf_path.exists():
            logger.warning(f"Category PDF not found for '{category}' — run generate_category_resumes.py first")
            continue

        application.state = ApplicationState.tailored
        application.resume_path = str(pdf_path)
        await _record_transition(db, application, ApplicationState.tailored, "tailoring_pass")
        count += 1

    await db.commit()
    return count


async def run_executor_pass(db: AsyncSession, dry_run: bool = False) -> dict:
    """Execute applications for tailored, human-approved postings."""
    submitted_count = await get_submitted_count(db)

    result = await db.execute(
        select(Application)
        .join(Posting)
        .where(
            Application.state.in_([
                ApplicationState.tailored,
                ApplicationState.human_review,
            ])
        )
        .options(selectinload(Application.posting).selectinload(Posting.company))
        .order_by(Posting.rank_score.desc())
        .limit(20)
    )
    applications = result.scalars().all()

    stats = {"attempted": 0, "submitted": 0, "human_queue": 0, "failed": 0}

    for app in applications:
        posting = app.posting
        company_slug = posting.company.slug if posting.company else ""

        if not browser_session.can_apply_to_company(company_slug):
            logger.info(f"Rate limit: already applied to {company_slug} today")
            continue

        if app.state == ApplicationState.tailored and needs_human_approval(submitted_count):
            app.state = ApplicationState.human_review
            await _record_transition(db, app, ApplicationState.human_review, "approval_gate")
            stats["human_queue"] += 1
            continue

        if not app.resume_path or not Path(app.resume_path).exists():
            logger.warning(f"No resume for application {app.id}")
            continue

        ats_type = posting.company.ats_type.value if posting.company else "unknown"
        answers = app.answers or {}
        posting_dict = {
            "id": posting.id,
            "company": posting.company.name if posting.company else "",
            "title": posting.title,
            "content_text": posting.content_text or "",
        }

        stats["attempted"] += 1
        async with browser_session.BrowserSession() as sess:
            apply_url = posting.apply_url or ""
            if "linkedin.com" in apply_url:
                submit_result = await linkedin_adapter.apply(
                    sess, apply_url, Path(app.resume_path),
                    answers, posting_dict, dry_run=dry_run
                )
                # LinkedIn adapter may discover the real ATS URL
                if submit_result.get("failure_type") == "external_apply":
                    real_url = submit_result.get("external_url", "")
                    if real_url:
                        posting.apply_url = real_url
                        ats_type = _detect_ats(real_url)
                        submit_result = await _dispatch_ats(
                            sess, ats_type, real_url, Path(app.resume_path),
                            answers, posting_dict, dry_run=dry_run
                        )
            elif ats_type == "greenhouse":
                submit_result = await greenhouse.apply(
                    sess, apply_url, Path(app.resume_path),
                    answers, posting_dict, dry_run=dry_run
                )
            elif ats_type == "lever":
                submit_result = await lever.apply(
                    sess, apply_url, Path(app.resume_path),
                    answers, posting_dict, dry_run=dry_run
                )
            else:
                submit_result = await _generic_apply(
                    sess, apply_url, Path(app.resume_path),
                    answers, posting_dict, dry_run=dry_run
                )

        if submit_result["success"]:
            app.state = ApplicationState.submitted
            app.submitted_at = utcnow()
            if submit_result.get("screenshot"):
                app.confirmation_screenshot = str(submit_result["screenshot"])
            browser_session.mark_applied_to_company(company_slug)
            submitted_count += 1
            stats["submitted"] += 1
            await _record_transition(db, app, ApplicationState.submitted, "executor")
        else:
            failure = submit_result.get("failure_type", "submit_failed")
            app.failure_type = FailureType(failure) if failure in [f.value for f in FailureType] else FailureType.submit_failed
            app.failure_detail = submit_result.get("error", "")

            if failure in ("captcha", "login_wall"):
                app.state = ApplicationState.human_review
                await _record_transition(db, app, ApplicationState.human_review, failure)
            stats["failed"] += 1

    await db.commit()
    logger.info(f"Executor pass: {stats}")
    return stats


def _detect_ats(url: str) -> str:
    if "greenhouse.io" in url or "boards.greenhouse" in url:
        return "greenhouse"
    if "lever.co" in url:
        return "lever"
    if "ashbyhq.com" in url:
        return "ashby"
    return "unknown"


async def _dispatch_ats(session, ats_type: str, url: str, resume_path, answers, posting, dry_run=False) -> dict:
    if ats_type == "greenhouse":
        return await greenhouse.apply(session, url, resume_path, answers, posting, dry_run=dry_run)
    if ats_type == "lever":
        return await lever.apply(session, url, resume_path, answers, posting, dry_run=dry_run)
    return await _generic_apply(session, url, resume_path, answers, posting, dry_run=dry_run)


async def _generic_apply(session, apply_url, resume_path, answers, posting, dry_run=False) -> dict:
    """Fallback generic apply using Stagehand agent.execute."""
    result = {"success": False, "screenshot": None, "failure_type": None}
    try:
        await session.goto(apply_url)
        await session.page.wait_for_load_state("networkidle", timeout=15000)

        await session.act(f"Fill the job application form with: Name={settings.applicant_name}, Email={settings.applicant_email}, Phone={settings.applicant_phone}, Location=Delhi India")
        await session.upload_file('input[type="file"]', resume_path)

        screenshot_path = settings.screenshots_dir / f"{posting.get('id', 'unknown')}_generic_preflight.png"
        await session.screenshot(screenshot_path)
        result["screenshot"] = screenshot_path

        if not dry_run:
            await session.act("Submit the application")
            await session.page.wait_for_load_state("networkidle", timeout=10000)

        result["success"] = True
    except Exception as e:
        result["failure_type"] = "submit_failed"
        result["error"] = str(e)
    return result


async def _record_transition(db: AsyncSession, app: Application, to_state: ApplicationState, trigger: str):
    transition = StateTransition(
        application_id=app.id,
        from_state=app.state if app.state != to_state else None,
        to_state=to_state,
        trigger=trigger,
    )
    app.last_state_at = utcnow()
    db.add(transition)
