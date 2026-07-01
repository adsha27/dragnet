"""
Greenhouse form adapter using direct Playwright selectors.
Standard Greenhouse fields are predictable; custom questions use get_by_label().
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

# Ordered selector lists for each standard field
_SELECTORS = {
    "first_name": ["#first_name", 'input[name*="first_name"]', 'input[autocomplete="given-name"]'],
    "last_name":  ["#last_name",  'input[name*="last_name"]',  'input[autocomplete="family-name"]'],
    "email":      ["#email", 'input[type="email"]', 'input[name*="email"]', 'input[id*="email"]', 'input[autocomplete="email"]', 'input[placeholder*="email" i]'],
    "phone":      ["#phone",      'input[type="tel"]',          'input[name*="phone"]'],
    "linkedin":   ['input[name*="linkedin"]', 'input[id*="linkedin"]'],
    "website":    ['input[name*="website"]',  'input[id*="website"]', 'input[name*="github"]'],
    "location":   ['input[name*="location"]', 'input[id*="location"]', 'input[name*="city"]'],
}

_STANDARD_FIELD_NAMES = {
    "first_name", "last_name", "email", "phone", "resume",
    "linkedin", "twitter", "github", "website", "portfolio",
    "cover_letter", "location", "city",
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

        body_text = (await page.inner_text("body")).lower()

        # Dead posting
        if "no longer open" in body_text or "job is closed" in body_text or "position has been filled" in body_text:
            result["failure_type"] = "dead_posting"
            return result

        # Hard login wall — no form at all
        if "sign in" in body_text and not await page.query_selector("form"):
            result["failure_type"] = "login_wall"
            return result

        # Click Apply button if form isn't already visible (Greenhouse renders form in-place)
        form = await page.query_selector("form#application_form, form[data-testid*='application']")
        if not form:
            apply_btn = await page.query_selector(
                'a:has-text("Apply"), button:has-text("Apply"), a[href*="apply"]'
            )
            if apply_btn:
                await apply_btn.click()
                await page.wait_for_load_state("networkidle", timeout=10000)

        first, *rest = settings.applicant_name.split()
        last = rest[-1] if rest else ""
        await _fill(page, _SELECTORS["first_name"], first)
        await _fill(page, _SELECTORS["last_name"], last)
        # Preferred/chosen name field — just first name, not LLM
        for sel in ['input[id*="preferred"]', 'input[name*="preferred"]', 'input[placeholder*="preferred" i]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(first)
                    break
            except Exception:
                pass
        await _fill(page, _SELECTORS["email"], settings.applicant_email)
        await _fill(page, _SELECTORS["phone"], settings.applicant_phone)
        await _fill(page, _SELECTORS["location"], "Delhi, India")
        # Only fill social fields if explicitly configured — never fabricate
        if settings.applicant_linkedin:
            await _fill(page, _SELECTORS["linkedin"], settings.applicant_linkedin)
        await _fill(page, _SELECTORS["website"], settings.applicant_github or "")
        # Twitter/X — always clear, we don't have an account
        for sel in ['input[name*="twitter"]', 'input[id*="twitter"]', 'input[placeholder*="twitter" i]',
                    'input[name*="x_url"]', 'input[placeholder*="@" i]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill("")
            except Exception:
                pass

        await session.upload_file('input[type="file"]', resume_path)

        # Custom questions
        for question_text in await _extract_custom_questions(page):
            answer = _lookup_answer(question_text, answers) or await answer_custom_question(question_text, posting)
            if answer:
                await _fill_question(page, question_text, answer)

        # All required dropdowns: work auth, US state, acknowledgments, source
        await _handle_required_dropdowns(page)

        screenshot_name = f"{posting.get('id', 'unknown')}_{posting.get('company', 'co')}_preflight.png"
        screenshot_path = settings.screenshots_dir / screenshot_name
        await session.screenshot(screenshot_path)
        result["screenshot"] = screenshot_path

        if dry_run:
            logger.info(f"[DRY RUN] Would submit for {posting.get('company')}")
            result["success"] = True
            return result

        # Captcha check only matters at submit time
        if await page.query_selector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"]'):
            result["failure_type"] = "captcha"
            return result

        await _click_submit(page)
        await page.wait_for_load_state("networkidle", timeout=15000)

        content_after = await page.content()
        if any(p in content_after.lower() for p in ["thank you", "application received", "submitted", "confirmation"]):
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
            const standardFor = new Set([
                'first_name','last_name','email','phone','resume',
                'linkedin','twitter','github','website','portfolio',
                'cover_letter','location','city'
            ]);
            const standardLabel = new Set([
                'website','linkedin','twitter','github','portfolio',
                'cover letter','resume','first name','last name','preferred first name',
                'email','phone','location','city'
            ]);
            return Array.from(document.querySelectorAll('.field label, [class*="field"] label'))
                .filter(l => {
                    const f = (l.getAttribute('for') || '').toLowerCase();
                    const t = l.textContent.trim().toLowerCase();
                    if (Array.from(standardFor).some(s => f.includes(s))) return false;
                    if (Array.from(standardLabel).some(s => t === s || t.startsWith(s + ' '))) return false;
                    return true;
                })
                .map(l => l.textContent.trim())
                .filter(t => t.length > 5 && t.length < 300);
        }
    """)


_SKILLS_YES = {"python", "javascript", "typescript", "rest api", "graphql", "postgresql", "redis",
               "llm", "ai", "machine learning", "backend", "fastapi", "django", "sql", "async",
               "observability", "monitoring", "docker", "git", "linux", "bash", "scripting"}
_SKILLS_NO = {"golang", " go ", "go lang", "kubernetes", "k8s", "rust", "java ", " c++", "ruby",
              "rails", "swift", "ios", "android", "terraform", "ansible", "hadoop", "spark",
              "scala", "php", "perl", "coffeescript", "elm", "haskell", "erlang", "elixir"}


async def _handle_required_dropdowns(page: Page):
    """Answer all required select dropdowns: work auth, US state, skills, acknowledgments, source."""
    try:
        selects = await page.query_selector_all("select")
        for sel in selects:
            label_text = await page.evaluate(
                "el => { const id = el.id; const l = document.querySelector(`label[for='${id}']`); return l ? l.textContent : el.closest('.field, .application-field')?.querySelector('label')?.textContent || ''; }",
                sel
            )
            t = label_text.lower()

            current = await sel.evaluate("el => el.value")
            if current and current != "":
                continue

            try:
                # Country/location
                if "which country" in t or ("country" in t and "working from" in t):
                    try:
                        await sel.select_option(label=re.compile("india", re.I))
                    except Exception:
                        await sel.select_option(label=re.compile("other", re.I))

                # Work sponsorship — yes, will need it
                elif "sponsor" in t and "visa" in t:
                    await sel.select_option(label=re.compile("yes", re.I))
                elif "sponsor" in t:
                    await sel.select_option(label=re.compile("yes|i may|future|possibly", re.I))

                # US work authorization — No (based in India)
                elif ("authoriz" in t and ("us " in t or "united states" in t)) or \
                     ("legally" in t and "work" in t and ("us" in t or "united states" in t)):
                    await sel.select_option(label=re.compile("no", re.I))

                # US state residency check
                elif "do you live in one of the following states" in t or \
                     ("live in" in t and "states" in t):
                    await sel.select_option(label=re.compile("no", re.I))

                # Employment agreements / non-compete / restrictions
                elif "employment agreement" in t or "non.compete" in t or \
                     "post.employment" in t or "restriction" in t:
                    await sel.select_option(label=re.compile("no", re.I))

                # "Previously worked at / consulted for <company>"
                elif ("previously worked" in t or "worked at" in t or "consulted for" in t or
                      "prior employer" in t or "former employee" in t):
                    await sel.select_option(label=re.compile("no", re.I))

                # Skill yes/no dropdowns
                elif any(skill in t for skill in _SKILLS_YES):
                    await sel.select_option(label=re.compile("yes", re.I))
                elif any(skill in t for skill in _SKILLS_NO):
                    await sel.select_option(label=re.compile("no", re.I))

                # Acknowledgment/confirmation
                elif "acknowledge" in t or "privacy" in t or "confirm" in t or \
                     "double.check" in t or "accuracy" in t:
                    try:
                        await sel.select_option(label=re.compile("yes|i agree|i confirm|i acknowledge", re.I))
                    except Exception:
                        opts = await sel.evaluate("el => Array.from(el.options).filter(o => o.value).map(o => o.value)")
                        if opts:
                            await sel.select_option(value=opts[0])

                # "Where did you hear about this role?"
                elif "hear" in t or "find out" in t or "source" in t or "referral" in t:
                    try:
                        await sel.select_option(label=re.compile("linkedin|job board|internet|online|other", re.I))
                    except Exception:
                        opts = await sel.evaluate("el => Array.from(el.options).filter(o => o.value).map(o => o.value)")
                        if opts:
                            await sel.select_option(value=opts[-1])

            except Exception:
                pass
    except Exception:
        pass


async def _click_submit(page: Page):
    for sel in [
        'input[type="submit"]',
        'button[type="submit"]',
        'button:has-text("Submit application")',
        'button:has-text("Submit")',
        'button:has-text("Apply")',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                return
        except Exception:
            continue


def _lookup_answer(question_text: str, answers: dict[str, str]) -> str:
    q = question_text.lower()
    for key, val in answers.items():
        if any(kw in q for kw in ["why", "project", "experience", "achievement"]) and val:
            return val
    return ""
