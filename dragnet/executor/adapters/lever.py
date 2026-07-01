"""
Lever form adapter using direct Playwright selectors.
Lever apply pages: jobs.lever.co/{slug}/{id}/apply
Standard fields: name, email, phone, org, resume, linkedin.
"""

import logging
import re
from pathlib import Path

from playwright.async_api import Page

from dragnet.config import settings
from dragnet.executor.session import BrowserSession
from dragnet.tailoring.answers import answer_custom_question
from dragnet.tailoring.unicode_normalize import normalize

logger = logging.getLogger(__name__)

_SELECTORS = {
    "name":     ['input[name="name"]',     'input[id*="name"]:not([id*="last"]):not([id*="first"])'],
    "email":    ['input[name="email"]',    'input[type="email"]'],
    "phone":    ['input[name="phone"]',    'input[type="tel"]'],
    "org":      ['input[name="org"]',      'input[id*="org"]', 'input[placeholder*="company" i]'],
    "location": ['input[name="location"]', 'input[id*="location"]'],
    "linkedin": ['input[name="urls[LinkedIn]"]', 'input[id*="linkedin"]', 'input[placeholder*="linkedin" i]'],
}


async def apply(
    session: BrowserSession,
    apply_url: str,
    resume_path: Path,
    answers: dict[str, str],
    posting: dict,
    dry_run: bool = False,
) -> dict:
    result = {"success": False, "screenshot": None, "failure_type": None}
    page = session.page

    try:
        await session.goto(apply_url)
        await page.wait_for_load_state("networkidle", timeout=15000)

        content = await page.content()
        if "captcha" in content.lower():
            result["failure_type"] = "captcha"
            return result

        await _fill(page, _SELECTORS["name"],     settings.applicant_name)
        await _fill(page, _SELECTORS["email"],    settings.applicant_email)
        await _fill(page, _SELECTORS["phone"],    settings.applicant_phone)
        await _fill(page, _SELECTORS["org"],      "Right Walk Foundation")
        await _fill(page, _SELECTORS["location"], "Delhi, India")
        if settings.applicant_linkedin:
            await _fill(page, _SELECTORS["linkedin"], settings.applicant_linkedin)
        # Twitter — always blank
        for sel in ['input[name*="twitter"]', 'input[name="urls[Twitter]"]',
                    'input[id*="twitter"]', 'input[placeholder*="twitter" i]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill("")
            except Exception:
                pass

        await session.upload_file('input[type="file"]', resume_path)

        for question_text in await _extract_custom_questions(page):
            answer = await answer_custom_question(question_text, posting)
            if answer:
                await _fill_question(page, question_text, answer)

        screenshot_name = f"{posting.get('id', 'unknown')}_{posting.get('company', 'co')}_preflight.png"
        screenshot_path = settings.screenshots_dir / screenshot_name
        await session.screenshot(screenshot_path)
        result["screenshot"] = screenshot_path

        if dry_run:
            result["success"] = True
            return result

        await _click_submit(page)
        await page.wait_for_load_state("networkidle", timeout=15000)

        content_after = await page.content()
        if any(p in content_after.lower() for p in ["thank you", "application submitted", "received", "we'll be in touch"]):
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


async def _fill(page: Page, selectors: list[str], value: str) -> bool:
    if not value:
        return False
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(normalize(value))
                return True
        except Exception:
            continue
    return False


async def _fill_question(page: Page, question_text: str, answer: str):
    try:
        locator = page.get_by_label(question_text[:80], exact=False)
        if await locator.count() == 0:
            return
        el = locator.first
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            try:
                await el.select_option(label=re.compile(answer[:30], re.I))
            except Exception:
                pass
        else:
            await el.fill(normalize(answer))
    except Exception:
        pass


async def _extract_custom_questions(page: Page) -> list[str]:
    return await page.evaluate("""
        () => {
            const standard = new Set(['name','email','phone','org','location','resume','linkedin','twitter','github','portfolio','website']);
            return Array.from(document.querySelectorAll('.application-field label, [class*="field"] label, form label'))
                .filter(l => {
                    const f = (l.getAttribute('for') || '').toLowerCase();
                    const t = l.textContent.trim().toLowerCase();
                    return !Array.from(standard).some(s => f.includes(s) || t === s);
                })
                .map(l => l.textContent.trim())
                .filter(t => t.length > 5 && t.length < 300);
        }
    """)


async def _click_submit(page: Page):
    for sel in [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit application")',
        'button:has-text("Submit")',
        'button:has-text("Apply now")',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                return
        except Exception:
            continue
