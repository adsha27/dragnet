"""
LinkedIn Easy Apply adapter.
Handles LinkedIn Easy Apply modal — the only way to apply to LinkedIn-only jobs.
Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env.

Flow: log in once (per process) → navigate to job → click Easy Apply → fill modal → submit.
"""

import json
import logging
from pathlib import Path

from dragnet.config import settings
from dragnet.executor.session import BrowserSession
from dragnet.tailoring.answers import answer_custom_question
from dragnet.tailoring.unicode_normalize import normalize

logger = logging.getLogger(__name__)

_LINKEDIN_LOGGED_IN = False
_COOKIE_FILE = Path("output/linkedin_cookies.json")


async def apply(
    session: BrowserSession,
    apply_url: str,
    resume_path: Path,
    answers: dict[str, str],
    posting: dict,
    dry_run: bool = False,
) -> dict:
    result = {"success": False, "screenshot": None, "failure_type": None}

    if not settings.linkedin_email or not settings.linkedin_password:
        result["failure_type"] = "no_linkedin_credentials"
        logger.error("LINKEDIN_EMAIL and LINKEDIN_PASSWORD must be set in .env")
        return result

    try:
        page = session.page
        if not page:
            result["failure_type"] = "no_playwright_page"
            return result

        # Inject saved cookies first (avoids re-login and checkpoint every session)
        await _inject_cookies(page)

        # Log in if not already authenticated via cookies
        if not _LINKEDIN_LOGGED_IN:
            await _login(session)

        # Navigate to job posting
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for main content — not networkidle (LinkedIn never settles)
        try:
            await page.wait_for_selector("main, #main, .jobs-details", timeout=10000)
        except Exception:
            pass

        page_content = await page.content()

        # Still getting login wall after login attempt
        if _is_login_wall(page_content) and "easy apply" not in page_content.lower():
            result["failure_type"] = "login_failed"
            logger.error("LinkedIn login wall persists after login attempt")
            return result

        # Detect Easy Apply vs external apply
        if "easy apply" not in page_content.lower():
            try:
                # Try to find an external apply link via Playwright directly
                el = await page.query_selector('a[href*="apply"], button:has-text("Apply")')
                href = await el.get_attribute("href") if el else None
                if href and "linkedin.com" not in href:
                    result["failure_type"] = "external_apply"
                    result["external_url"] = href
                else:
                    result["failure_type"] = "no_easy_apply"
            except Exception:
                result["failure_type"] = "no_easy_apply"
            return result

        # Click Easy Apply button
        easy_apply_btn = await page.query_selector(
            'button:has-text("Easy Apply"), .jobs-apply-button'
        )
        if easy_apply_btn:
            await easy_apply_btn.click()
        else:
            await page.click('button:has-text("Easy Apply")')
        await page.wait_for_timeout(2000)

        # Fill the modal
        await _fill_easy_apply_modal(session, resume_path, answers, posting)

        # Screenshot before submit
        screenshot_name = f"{posting.get('id', 'unknown')}_{posting.get('company', 'co')}_linkedin_preflight.png"
        screenshot_path = settings.screenshots_dir / screenshot_name
        await session.screenshot(screenshot_path)
        result["screenshot"] = screenshot_path

        if dry_run:
            logger.info(f"[DRY RUN] Would submit LinkedIn Easy Apply for {posting.get('company')}")
            dismiss = await page.query_selector('button[aria-label="Dismiss"], button:has-text("Discard")')
            if dismiss:
                await dismiss.click()
            result["success"] = True
            return result

        # Submit
        submit_btn = await page.query_selector('button:has-text("Submit application")')
        if submit_btn:
            await submit_btn.click()
        else:
            await page.click('button:has-text("Submit")')
        await page.wait_for_timeout(3000)

        content_after = await page.content()
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

    except RuntimeError as e:
        if "linkedin_checkpoint" in str(e):
            result["failure_type"] = "captcha"
            result["error"] = "LinkedIn security checkpoint — complete it manually then re-run"
        else:
            result["failure_type"] = "unknown_error"
            result["error"] = str(e)
    except Exception as e:
        logger.error(f"LinkedIn Easy Apply failed for {apply_url}: {e}")
        result["failure_type"] = "unknown_error"
        result["error"] = str(e)

    return result


async def _inject_cookies(page) -> None:
    if not _COOKIE_FILE.exists():
        return
    try:
        cookies = json.loads(_COOKIE_FILE.read_text())
        await page.context.add_cookies(cookies)
        logger.info(f"Injected {len(cookies)} LinkedIn cookies")
    except Exception as e:
        logger.warning(f"Cookie injection failed: {e}")


async def _save_cookies(page) -> None:
    try:
        _COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        cookies = await page.context.cookies()
        _COOKIE_FILE.write_text(json.dumps(cookies, indent=2))
        logger.info(f"Saved {len(cookies)} LinkedIn cookies to {_COOKIE_FILE}")
    except Exception as e:
        logger.warning(f"Cookie save failed: {e}")


def _is_login_wall(content: str) -> bool:
    lc = content.lower()
    return ("sign in" in lc or "join now" in lc) and "feed" not in lc


async def _login(session: BrowserSession) -> None:
    global _LINKEDIN_LOGGED_IN
    if _LINKEDIN_LOGGED_IN:
        return

    page = session.page
    # Use "load" (not domcontentloaded) so React has time to render the form
    await page.goto("https://www.linkedin.com/login", wait_until="load", timeout=45000)
    logger.info(f"LinkedIn login page URL: {page.url}")

    # Wait for any email input to be attached (form renders before it's visible)
    try:
        await page.wait_for_selector('input[type="email"]', state="attached", timeout=20000)
    except Exception:
        url = page.url
        logger.warning(f"No login form found at {url}")
        if "feed" in url or "mynetwork" in url:
            _LINKEDIN_LOGGED_IN = True
            logger.info("LinkedIn already logged in")
        return

    # LinkedIn renders duplicate forms; find the visible one via JS.
    # Use React's native value setter to trigger onChange (plain .value= doesn't work).
    filled = await page.evaluate("""([email, password]) => {
        const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        const visible = el => { const r = el.getBoundingClientRect(); return r.width > 5 && r.height > 5; };
        const emailEl = [...document.querySelectorAll('input[type="email"]')].find(visible);
        const pwdEl   = [...document.querySelectorAll('input[type="password"]')].find(visible);
        if (!emailEl || !pwdEl) return false;
        nativeSetter.call(emailEl, email);
        emailEl.dispatchEvent(new Event('input', {bubbles:true}));
        emailEl.dispatchEvent(new Event('change', {bubbles:true}));
        nativeSetter.call(pwdEl, password);
        pwdEl.dispatchEvent(new Event('input', {bubbles:true}));
        pwdEl.dispatchEvent(new Event('change', {bubbles:true}));
        return true;
    }""", [settings.linkedin_email, settings.linkedin_password])

    if not filled:
        logger.warning("Could not fill LinkedIn login form — no visible inputs found")
        return

    logger.info("LinkedIn login form filled via React native setter")

    # Click the "Sign in" button (exact match to avoid "Sign in with Apple")
    try:
        await page.get_by_role("button", name="Sign in", exact=True).first.click(
            force=True, timeout=8000
        )
    except Exception:
        logger.warning("Could not click Sign in button")
        return

    try:
        await page.wait_for_url(
            lambda url: any(s in url for s in ("feed", "checkpoint", "mynetwork", "challenge", "authwall")),
            timeout=20000,
        )
    except Exception:
        pass

    url = page.url
    logger.info(f"LinkedIn post-login URL: {url}")
    if "feed" in url or "mynetwork" in url:
        _LINKEDIN_LOGGED_IN = True
        logger.info("LinkedIn login successful")
        # Save cookies so future sessions skip login
        await _save_cookies(page)
    elif "checkpoint" in url or "challenge" in url:
        logger.warning("LinkedIn security checkpoint — manual verification needed. "
                       "Complete it in the Browserbase live view, then re-run.")
        raise RuntimeError("linkedin_checkpoint")
    else:
        logger.warning(f"LinkedIn login uncertain — URL: {url}")


async def _fill_easy_apply_modal(
    session: BrowserSession,
    resume_path: Path,
    answers: dict[str, str],
    posting: dict,
) -> None:
    page = session.page

    for step in range(6):
        content = await page.content()

        # Phone number
        if "phone" in content.lower() or "mobile" in content.lower():
            phone_input = await page.query_selector('input[name*="phone"], input[id*="phone"], input[placeholder*="phone"]')
            if phone_input:
                val = await phone_input.input_value()
                if not val:
                    await phone_input.fill(settings.applicant_phone)

        # Resume upload
        file_input = await page.query_selector('input[type="file"]')
        if file_input:
            await file_input.set_input_files(str(resume_path))

        # Screening questions — labels with associated inputs
        labels = await page.query_selector_all("label")
        for label in labels:
            label_text = (await label.inner_text()).strip()
            if not label_text or len(label_text) < 5:
                continue
            standard = {"first name", "last name", "email", "phone", "mobile",
                        "location", "city", "resume", "cover letter", "linkedin",
                        "website", "portfolio", "upload"}
            if any(s in label_text.lower() for s in standard):
                continue
            answer = answers.get(label_text) or await answer_custom_question(label_text, posting)
            if not answer:
                continue
            # Find the input associated with this label
            for_ = await label.get_attribute("for")
            if for_:
                inp = await page.query_selector(f"#{for_}")
                if inp:
                    tag = await inp.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "select":
                        await inp.select_option(label=answer)
                    elif tag in ("input", "textarea"):
                        await inp.fill(answer)

        # Work authorization
        if "authorized" in content.lower() or "sponsorship" in content.lower():
            auth_inputs = await page.query_selector_all('input[type="radio"], select')
            for inp in auth_inputs:
                label_text = await page.evaluate(
                    "el => { const l = document.querySelector(`label[for='${el.id}']`); return l ? l.innerText : ''; }",
                    inp
                )
                if "authorized" in (label_text or "").lower() and "india" in (label_text or "").lower():
                    await inp.check() if await inp.get_attribute("type") == "radio" else None

        # Ready to submit
        if "review" in content.lower() and "submit" in content.lower():
            break

        # Next step
        next_btn = await page.query_selector(
            'button:has-text("Next"), button:has-text("Continue"), button:has-text("Review")'
        )
        if next_btn:
            await next_btn.click()
            await page.wait_for_timeout(1500)
        else:
            break
