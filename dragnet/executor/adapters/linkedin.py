"""
LinkedIn Easy Apply adapter.
Handles LinkedIn Easy Apply modal — the only way to apply to LinkedIn-only jobs.
Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env.

Flow: navigate to job → log in if needed → click Easy Apply → fill modal steps → submit.
LinkedIn Easy Apply is always the same multi-step modal: contact info, resume, questions, review.
"""

import logging
from pathlib import Path

from dragnet.config import settings
from dragnet.executor.session import BrowserSession
from dragnet.tailoring.answers import answer_custom_question
from dragnet.tailoring.unicode_normalize import normalize

logger = logging.getLogger(__name__)

_LINKEDIN_LOGGED_IN = False  # module-level flag; reset per process


async def apply(
    session: BrowserSession,
    apply_url: str,
    resume_path: Path,
    answers: dict[str, str],
    posting: dict,
    dry_run: bool = False,
) -> dict:
    """
    Submit a LinkedIn Easy Apply application.
    Returns {"success": bool, "screenshot": Path, "failure_type": str | None}
    """
    result = {"success": False, "screenshot": None, "failure_type": None}

    if not settings.linkedin_email or not settings.linkedin_password:
        result["failure_type"] = "no_linkedin_credentials"
        logger.error("LINKEDIN_EMAIL and LINKEDIN_PASSWORD must be set in .env")
        return result

    try:
        await session.goto(apply_url)
        await session.page.wait_for_load_state("networkidle", timeout=15000)

        # Log in if not already authenticated
        page_content = await session.page.content()
        if "sign in" in page_content.lower() or "join now" in page_content.lower():
            await _login(session)
            await session.page.wait_for_load_state("networkidle", timeout=15000)
            page_content = await session.page.content()

        # Check for login wall still present
        if "sign in" in page_content.lower() and "easy apply" not in page_content.lower():
            result["failure_type"] = "login_failed"
            return result

        # Detect Easy Apply vs external apply
        if "easy apply" not in page_content.lower():
            # This job redirects to company website — extract the URL and report it
            ext = await session.extract(
                "Find the job application URL or 'Apply on company website' link. Return the URL only."
            )
            if ext and "linkedin.com" not in str(ext):
                result["failure_type"] = "external_apply"
                result["external_url"] = str(ext).strip()
            else:
                result["failure_type"] = "no_easy_apply"
            return result

        # Click Easy Apply button
        await session.act("Click the 'Easy Apply' button to open the application modal")
        await session.page.wait_for_timeout(2000)

        # Fill the modal — LinkedIn Easy Apply is 2-4 steps
        await _fill_easy_apply_modal(session, resume_path, answers, posting)

        # Screenshot before submit
        screenshot_name = f"{posting.get('id', 'unknown')}_{posting.get('company', 'co')}_linkedin_preflight.png"
        screenshot_path = settings.screenshots_dir / screenshot_name
        await session.screenshot(screenshot_path)
        result["screenshot"] = screenshot_path

        if dry_run:
            logger.info(f"[DRY RUN] Would submit LinkedIn Easy Apply for {posting.get('company')}")
            # Close modal without submitting
            await session.act("Click the close or discard button to exit the application modal without submitting")
            result["success"] = True
            return result

        # Submit
        await session.act("Click the 'Submit application' or 'Review' button to submit")
        await session.page.wait_for_timeout(3000)

        # Confirm submission
        content_after = await session.page.content()
        submitted = any(
            phrase in content_after.lower()
            for phrase in ["application submitted", "your application was sent", "you've applied"]
        )

        if submitted:
            confirm_path = settings.screenshots_dir / screenshot_name.replace("_preflight", "_confirm")
            await session.screenshot(confirm_path)
            result["success"] = True
            result["screenshot"] = confirm_path
        else:
            result["failure_type"] = "submit_failed"

    except Exception as e:
        logger.error(f"LinkedIn Easy Apply failed for {apply_url}: {e}")
        result["failure_type"] = "unknown_error"
        result["error"] = str(e)

    return result


async def _login(session: BrowserSession) -> None:
    """Log in to LinkedIn with credentials from settings."""
    global _LINKEDIN_LOGGED_IN
    if _LINKEDIN_LOGGED_IN:
        return

    await session.goto("https://www.linkedin.com/login")
    await session.page.wait_for_load_state("networkidle", timeout=10000)

    await session.act(normalize(
        f"Fill the email field with '{settings.linkedin_email}' "
        f"and the password field with '{settings.linkedin_password}', then click Sign in"
    ))
    await session.page.wait_for_load_state("networkidle", timeout=15000)

    # Check if login succeeded
    content = await session.page.content()
    if "feed" in session.page.url or "mynetwork" in session.page.url:
        _LINKEDIN_LOGGED_IN = True
        logger.info("LinkedIn login successful")
    elif "checkpoint" in session.page.url or "challenge" in session.page.url:
        logger.warning("LinkedIn security checkpoint hit — may need manual verification")
        _LINKEDIN_LOGGED_IN = False
    else:
        logger.warning(f"LinkedIn login uncertain — URL: {session.page.url}")


async def _fill_easy_apply_modal(
    session: BrowserSession,
    resume_path: Path,
    answers: dict[str, str],
    posting: dict,
) -> None:
    """Fill all steps of the LinkedIn Easy Apply modal."""
    for step in range(6):  # LinkedIn Easy Apply has at most ~4 steps
        content = await session.page.content()

        # Contact info step
        if "phone" in content.lower() or "mobile" in content.lower():
            await session.act(normalize(
                f"Fill phone/mobile number with '{settings.applicant_phone}' if the field is empty"
            ))

        # Resume step — upload PDF
        if 'input[type="file"]' in content or "resume" in content.lower() or "upload" in content.lower():
            try:
                await session.upload_file('input[type="file"]', resume_path)
            except Exception:
                await session.act(normalize(f"Upload resume from path: {resume_path}"))

        # Screening questions
        questions = await _extract_modal_questions(session, content)
        for q in questions:
            answer = answers.get(q) or await answer_custom_question(q, posting)
            if answer:
                await session.act(normalize(
                    f"Answer the question '{q[:80]}' with: {answer}"
                ))

        # Work authorization
        if "authorized" in content.lower() or "sponsorship" in content.lower() or "visa" in content.lower():
            await session.act(
                "For work authorization: if asked about authorization for India, select Yes. "
                "If asked about US/UK/EU authorization or needing sponsorship for those, "
                "fill with: 'I am based in India, available as contractor or via EOR arrangement'"
            )

        # Location/address
        if "city" in content.lower() or "location" in content.lower():
            await session.act(normalize(
                f"If there is a city or current location field, fill it with 'Delhi, India'"
            ))

        # Navigate to next step or detect if we're on review
        if "review" in content.lower() and "submit" in content.lower():
            break  # Ready to submit — caller handles this

        next_clicked = await _click_next(session, content)
        if not next_clicked:
            break

        await session.page.wait_for_timeout(1500)


async def _click_next(session: BrowserSession, content: str) -> bool:
    """Click Next/Continue in the modal. Returns False if no next button found."""
    try:
        if "next" in content.lower() or "continue" in content.lower():
            await session.act("Click the 'Next' or 'Continue' button in the application modal")
            return True
    except Exception:
        pass
    return False


async def _extract_modal_questions(session: BrowserSession, content: str) -> list[str]:
    """Extract custom screening question text from the Easy Apply modal."""
    # Standard LinkedIn fields we handle separately
    standard = {"first name", "last name", "email", "phone", "mobile", "location", "city",
                 "resume", "cover letter", "linkedin", "website", "portfolio", "upload"}

    try:
        data = await session.extract(
            "List all question labels in the current application form step. "
            "Exclude standard fields like name, email, phone, resume upload. "
            "Return only custom screening question text."
        )
        if isinstance(data, list):
            return [
                str(q) for q in data
                if q and not any(s in str(q).lower() for s in standard)
            ]
        elif isinstance(data, str) and data.strip():
            return [data.strip()]
    except Exception:
        pass
    return []
