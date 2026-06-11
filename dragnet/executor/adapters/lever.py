"""
Lever form adapter.
Lever apply pages are hosted at jobs.lever.co/{slug}/{posting_id}/apply
Standard fields: name, email, phone, org/company, resume, cover letter, custom questions.
"""

import logging
from pathlib import Path

from dragnet.config import settings
from dragnet.executor.session import BrowserSession
from dragnet.tailoring.answers import answer_custom_question

logger = logging.getLogger(__name__)


async def apply(
    session: BrowserSession,
    apply_url: str,
    resume_path: Path,
    answers: dict[str, str],
    posting: dict,
    dry_run: bool = False,
) -> dict:
    result = {"success": False, "screenshot": None, "failure_type": None}

    try:
        await session.goto(apply_url)
        await session.page.wait_for_load_state("networkidle", timeout=15000)

        page_content = await session.page.content()
        if "captcha" in page_content.lower():
            result["failure_type"] = "captcha"
            return result

        # Standard Lever fields
        await session.act(f"Fill the full name field with '{settings.applicant_name}'")
        await session.act(f"Fill the email field with '{settings.applicant_email}'")
        await session.act(f"Fill the phone field with '{settings.applicant_phone}'")

        # Current company / org (optional on Lever)
        await session.act("If there is a current company or organization field, fill it with 'Right Walk Foundation'")

        # Location
        await session.act("If there is a location field, fill it with 'Delhi, India'")

        # Resume
        try:
            await session.upload_file('input[type="file"]', resume_path)
        except Exception:
            await session.act(f"Upload file: {resume_path}")

        # LinkedIn
        await session.act("If there is a LinkedIn profile URL field, leave it blank or skip")

        # Custom questions
        custom_questions = await _extract_lever_questions(session)
        for question_text in custom_questions:
            answer = await answer_custom_question(question_text, posting)
            if answer:
                await session.act(
                    f"Find the question '{question_text[:80]}' and fill its answer field with: {answer}"
                )

        # Screenshot pre-submit
        screenshot_name = f"{posting.get('id', 'unknown')}_{posting.get('company', 'co')}_preflight.png"
        screenshot_path = settings.screenshots_dir / screenshot_name
        await session.screenshot(screenshot_path)
        result["screenshot"] = screenshot_path

        if dry_run:
            result["success"] = True
            return result

        await session.act("Submit the application form")
        await session.page.wait_for_load_state("networkidle", timeout=15000)

        content_after = await session.page.content()
        submitted = any(
            phrase in content_after.lower()
            for phrase in ["thank you", "application submitted", "received", "we'll be in touch"]
        )

        if submitted:
            confirm_path = settings.screenshots_dir / screenshot_name.replace("_preflight", "_confirm")
            await session.screenshot(confirm_path)
            result["success"] = True
            result["screenshot"] = confirm_path
        else:
            result["failure_type"] = "submit_failed"

    except Exception as e:
        logger.error(f"Lever apply failed for {apply_url}: {e}")
        result["failure_type"] = "unknown_field"
        result["error"] = str(e)

    return result


async def _extract_lever_questions(session: BrowserSession) -> list[str]:
    try:
        data = await session.extract(
            "List all custom question labels in this Lever application form. "
            "Skip standard fields (name, email, phone, company, location, resume). "
            "Return question texts only."
        )
        if isinstance(data, list):
            return [str(q) for q in data if q]
    except Exception:
        pass
    return []
