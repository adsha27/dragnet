"""
Greenhouse form adapter.
Greenhouse application forms are fairly uniform.
Standard fields: name, email, phone, resume upload, cover letter, custom questions.
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
    """
    Fill and submit a Greenhouse application.
    Returns {"success": bool, "screenshot": Path, "failure_type": str | None}
    """
    result = {"success": False, "screenshot": None, "failure_type": None}

    try:
        await session.goto(apply_url)
        await session.page.wait_for_load_state("networkidle", timeout=15000)

        # Check for captcha / login wall
        page_content = await session.page.content()
        if "captcha" in page_content.lower() or "recaptcha" in page_content.lower():
            result["failure_type"] = "captcha"
            return result
        if "sign in" in page_content.lower() and "apply" not in page_content.lower():
            result["failure_type"] = "login_wall"
            return result

        # Fill standard fields
        await session.act(f"Fill the first name field with '{_first_name()}'")
        await session.act(f"Fill the last name field with '{_last_name()}'")
        await session.act(f"Fill the email field with '{settings.applicant_email}'")
        await session.act(f"Fill the phone field with '{settings.applicant_phone}'")

        # Location / address if asked
        await session.act(f"If there is a location or city field, fill it with 'Delhi, India'")

        # Resume upload
        try:
            await session.upload_file('input[type="file"]', resume_path)
        except Exception:
            await session.act(f"Upload the resume file at path: {resume_path}")

        # LinkedIn / portfolio
        await session.act(f"If there is a LinkedIn URL field, fill it with an empty value or skip it")
        await session.act(f"If there is a website or portfolio field, fill it with '{settings.applicant_github}'")

        # Cover letter
        await session.act("If there is a cover letter text area, leave it empty or fill with a single space")

        # Custom questions from the form
        custom_questions = await _extract_custom_questions(session)
        for question_text in custom_questions:
            q_lower = question_text.lower()
            answer = ""

            # Check if we have a pre-generated answer
            for pre_q, pre_a in answers.items():
                if any(kw in q_lower for kw in ["why", "project", "experience", "achievement"]):
                    if pre_a:
                        answer = pre_a
                        break

            # Generate on the fly if needed
            if not answer:
                answer = await answer_custom_question(question_text, posting)

            if answer:
                await session.act(
                    f"Fill the question '{question_text[:80]}' with the answer: {answer}"
                )

        # Work authorization / visa questions
        await session.act(
            "If asked about work authorization or visa sponsorship, "
            "select 'No' for US work authorization and 'Yes' for needing sponsorship, "
            "OR if the form has a text field, enter: "
            "'I am based in India and available to work as a contractor or via EOR'"
        )

        # Screenshot before submit
        screenshot_name = f"{posting.get('id', 'unknown')}_{posting.get('company', 'co')}_preflight.png"
        screenshot_path = settings.screenshots_dir / screenshot_name
        await session.screenshot(screenshot_path)
        result["screenshot"] = screenshot_path

        if dry_run:
            logger.info(f"[DRY RUN] Would submit for {posting.get('company')}")
            result["success"] = True
            return result

        # Submit
        await session.act("Click the submit application button")
        await session.page.wait_for_load_state("networkidle", timeout=15000)

        # Confirm
        content_after = await session.page.content()
        submitted = any(
            phrase in content_after.lower()
            for phrase in ["thank you", "application received", "submitted", "confirmation"]
        )

        if submitted:
            confirm_path = settings.screenshots_dir / screenshot_name.replace("_preflight", "_confirm")
            await session.screenshot(confirm_path)
            result["success"] = True
            result["screenshot"] = confirm_path
        else:
            result["failure_type"] = "submit_failed"

    except Exception as e:
        logger.error(f"Greenhouse apply failed for {apply_url}: {e}")
        result["failure_type"] = "unknown_field"
        result["error"] = str(e)

    return result


async def _extract_custom_questions(session: BrowserSession) -> list[str]:
    """Extract text of custom questions from the form."""
    try:
        data = await session.extract(
            "List all custom/additional question labels in the job application form. "
            "Return only question text, not standard fields like name/email/phone/resume."
        )
        if isinstance(data, list):
            return [str(q) for q in data if q]
        elif isinstance(data, str) and data.strip():
            return [data.strip()]
    except Exception:
        pass
    return []


def _first_name() -> str:
    return settings.applicant_name.split()[0]


def _last_name() -> str:
    parts = settings.applicant_name.split()
    return parts[-1] if len(parts) > 1 else ""
