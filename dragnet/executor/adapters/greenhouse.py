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
        if not await _fill(page, _SELECTORS["email"], settings.applicant_email):
            # React-controlled forms ignore fill() — use native value setter + dispatch events
            await page.evaluate(f"""() => {{
                const el = document.querySelector('#email')
                    || document.querySelector('input[type="email"]')
                    || document.querySelector('input[name*="email"]')
                    || document.querySelector('input[id*="email"]')
                    || Array.from(document.querySelectorAll('input')).find(i => {{
                        const l = document.querySelector(`label[for='${{i.id}}']`);
                        return l && l.textContent.toLowerCase().includes('email');
                    }});
                if (el) {{
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, '{settings.applicant_email}');
                    el.dispatchEvent(new Event('input', {{bubbles: true}}));
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}""")
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

        await _handle_required_dropdowns(page)
        # Click-based fallback for custom dropdown components (React Select, Select2, etc.)
        await _click_custom_dropdowns(page)

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
                await el.select_option(label=re.compile(re.escape(answer[:30]), re.I))
            except Exception:
                pass
        elif await el.evaluate("el => el.getAttribute('role') === 'combobox' || (el.className && el.className.includes('select__input'))"):
            await _react_pick(page, el, re.escape(answer))
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
              "scala", "php", "perl"}


async def _sel_opt(loc, *patterns: str) -> bool:
    """Try select_option with each pattern in order. Returns True if one succeeded."""
    for pat in patterns:
        try:
            await loc.select_option(label=re.compile(pat, re.I))
            return True
        except Exception:
            continue
    # Last resort: pick first non-empty option (for acknowledgments with only one real choice)
    try:
        opts = await loc.evaluate("el => Array.from(el.options).filter(o=>o.value).map(o=>o.value)")
        if opts:
            await loc.select_option(value=opts[0])
            return True
    except Exception:
        pass
    return False


async def _react_pick(page: Page, el, *option_patterns: str) -> bool:
    """Pick an option from a React Select combobox (click → type → click option)."""
    for pat in option_patterns:
        # Derive a plain search string: strip regex metacharacters, take first word
        search = re.sub(r"[|()*?+\\^$\[\]{}.]", " ", pat).strip().split()[0] if pat else ""
        try:
            # Skip if already filled
            val = await el.evaluate("""el => {
                const c = el.closest('.select-shell') || el.parentElement?.parentElement?.parentElement;
                return c?.querySelector('.select__single-value, .select__multi-value')?.textContent?.trim() || '';
            }""")
            if val and not re.match(r"^select|^choose", val, re.I):
                return True

            await el.click()
            await page.wait_for_timeout(300)

            if search:
                await el.type(search)
                await page.wait_for_timeout(300)

            opts = await page.query_selector_all(".select__option")
            re_pat = re.compile(pat, re.I)
            # Exact text match first to avoid false positives (e.g. "India" matching "British Indian Ocean Territory")
            for opt in opts:
                text = (await opt.inner_text()).strip()
                if text.lower() == search.lower():
                    await opt.click()
                    await page.wait_for_timeout(150)
                    return True
            # Regex fallback
            for opt in opts:
                text = (await opt.inner_text()).strip()
                if re_pat.search(text):
                    await opt.click()
                    await page.wait_for_timeout(150)
                    return True

            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
        except Exception:
            pass
    return False


async def _handle_required_dropdowns(page: Page):
    """Answer required select/combobox dropdowns using accessibility tree (get_by_role)."""

    # Build list of (label_pattern, answer_patterns, fallback_opts)
    rules = [
        # Country / nationality / residence
        (re.compile(r"which country|country.*work|country.*resid|nationality|current country|what country", re.I),
         ["india"], ["other"]),
        # US work authorization
        (re.compile(r"legally authorized.*united states|authorized to work.*us\b|work.*legally.*us\b", re.I),
         ["no"], []),
        # US state residency
        (re.compile(r"live in one of the following states|reside in.*state", re.I),
         ["no"], []),
        # Sponsorship
        (re.compile(r"require sponsorship|visa sponsorship|sponsor.*visa", re.I),
         ["yes", "i may", "future", "possibly"], []),
        # Employment restrictions
        (re.compile(r"employment agreement|non.compete|post.employment restriction", re.I),
         ["no"], []),
        # Previously worked at this company
        (re.compile(r"previously worked at|consulted for|former employee|prior employer", re.I),
         ["no"], []),
        # Privacy / acknowledgment
        (re.compile(r"privacy.*notice|privacy.*policy|acknowledge.*read|confirm.*read|agree.*terms|canonical.*privacy|confirm.*privacy", re.I),
         ["acknowledge", "yes", "i agree", "i confirm", "i acknowledge", "agree"], []),
        # Travel commitment
        (re.compile(r"willing.*able.*commit|commit to this|meet in person|willing.*travel|travel.*meet", re.I),
         ["yes"], []),
        # DEI / EEO — prefer not to say
        (re.compile(r"gender|ethnicity|race\b|veteran|disability", re.I),
         ["prefer not|decline|not to say|not wish|i don"], []),
        # How many companies
        (re.compile(r"how many companies|number of (?:previous )?employers", re.I),
         [r"^1$", r"^1 "], []),
        # Skills yes
        (re.compile(r"experience in python|proficiency.*python|experience.*javascript|experience.*typescript|"
                    r"llm ecosystem|experience.*rest api|experience.*graphql|experience.*backend|"
                    r"experience.*postgresql|experience.*redis|experience.*docker", re.I),
         ["yes"], []),
        # Skills no
        (re.compile(r"experience in go\b|experience.*golang|experience.*kubernetes|experience.*k8s|"
                    r"experience.*ruby|experience.*rails|experience.*rust\b|experience.*scala", re.I),
         ["no"], []),
        # Source / referral
        (re.compile(r"how did you hear|where did you hear|how did you find|referral source", re.I),
         ["linkedin", "job board", "internet", "online", "other"], []),
        # Location dropdown
        (re.compile(r"select.*location|current.*location|where.*located|location.*dropdown", re.I),
         ["india", "delhi", "remote"], []),
        # Double-check accuracy (Vercel-style)
        (re.compile(r"double.check|accuracy.*crucial|ensure accuracy", re.I),
         ["yes", "i confirm", "i acknowledge"], []),
    ]

    # Pass 1: get_by_role covers both native <select> and React Select comboboxes
    for label_pat, answer_pats, fallback_pats in rules:
        try:
            loc = page.get_by_role("combobox", name=label_pat)
            count = await loc.count()
            for i in range(count):
                el = loc.nth(i)
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    cur_text = await el.evaluate("el => (el.options[el.selectedIndex] || {}).text || ''")
                    if cur_text and not re.search(r"^select|^choose|^please select|^---", cur_text, re.I):
                        continue
                    await _sel_opt(el, *answer_pats, *fallback_pats)
                else:
                    await _react_pick(page, el, *answer_pats, *fallback_pats)
        except Exception:
            pass

    # Pass 2: single JS pass — find all unanswered selects, extract context, fill via native setter
    await page.evaluate("""() => {
        function getContext(sel) {
            if (sel.labels && sel.labels.length > 0)
                return Array.from(sel.labels).map(l => l.textContent).join(' ');
            const lb = sel.getAttribute('aria-labelledby');
            if (lb) return lb.split(' ').map(id => (document.getElementById(id)||{}).textContent||'').join(' ');
            const al = sel.getAttribute('aria-label');
            if (al) return al;
            const texts = [];
            let node = sel.previousElementSibling;
            while (node) { const t = node.textContent.trim(); if (t.length > 3) texts.push(t); node = node.previousElementSibling; }
            if (texts.length) return texts[texts.length - 1];
            const parent = sel.parentElement;
            if (parent) {
                node = parent.previousElementSibling;
                while (node) { const t = node.textContent.trim(); if (t.length > 3) return t; node = node.previousElementSibling; }
                const gp = parent.parentElement;
                if (gp) { node = gp.previousElementSibling; while (node) { const t = node.textContent.trim(); if (t.length > 3) return t; node = node.previousElementSibling; } }
            }
            return '';
        }
        function pickOpt(sel, ...patterns) {
            const opts = Array.from(sel.options).filter(o => o.value);
            for (const pat of patterns) {
                const re = new RegExp(pat, 'i');
                const opt = opts.find(o => re.test(o.text));
                if (opt) return opt;
            }
            return null;
        }
        function setVal(sel, opt) {
            if (!opt) return;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
            setter.call(sel, opt.value);
            sel.dispatchEvent(new Event('change', {bubbles: true}));
            sel.dispatchEvent(new Event('input', {bubbles: true}));
        }
        for (const sel of document.querySelectorAll('select')) {
            const curText = (sel.options[sel.selectedIndex] || {}).text || '';
            if (sel.value && !/^select|^choose|^please select|^---/i.test(curText.trim())) continue;
            const ctx = getContext(sel).toLowerCase();
            if (!ctx) continue;
            let opt = null;
            if (/which country|country.*work|country.*resid|nationality|current country|in which country/.test(ctx))
                opt = pickOpt(sel, 'india', 'other');
            else if (/privacy.*notice|privacy.*policy|confirm.*read|agree.*terms|canonical.*privacy/.test(ctx))
                opt = pickOpt(sel, 'yes', 'i agree', 'i confirm', 'agree') || Array.from(sel.options).filter(o=>o.value)[0];
            else if (/gender|ethnicity|race\\b|veteran|disability/.test(ctx))
                opt = pickOpt(sel, 'prefer not|not to say|decline|i don');
            else if (/sponsor.*visa|visa.*sponsor|require sponsorship/.test(ctx))
                opt = pickOpt(sel, 'yes', 'i may', 'future');
            else if (/legally authorized|authorized to work|work.*legally/.test(ctx))
                opt = pickOpt(sel, 'no');
            else if (/following states|live in.*states/.test(ctx))
                opt = pickOpt(sel, 'no');
            else if (/employment.?agreement|non.?compete|post.?employment/.test(ctx))
                opt = pickOpt(sel, 'no');
            else if (/previously worked|consulted for|former employee/.test(ctx))
                opt = pickOpt(sel, 'no');
            else if (/how many companies|number of.*employer/.test(ctx))
                opt = pickOpt(sel, '^1$', '^1 ', 'one');
            else if (/commit.*travel|travel.*meet|meet.*person|willing.*travel/.test(ctx))
                opt = pickOpt(sel, 'yes');
            else if (/how did you hear|where did you hear|referral source/.test(ctx))
                opt = pickOpt(sel, 'linkedin', 'job board', 'internet', 'other');
            else if (/double.check|accuracy.*crucial|ensure accuracy/.test(ctx))
                opt = pickOpt(sel, 'yes', 'i confirm');
            else if (/experience in go\\b|experience.*golang/.test(ctx))
                opt = pickOpt(sel, 'no');
            else if (/experience in kubernetes|experience.*k8s/.test(ctx))
                opt = pickOpt(sel, 'no');
            else if (/experience.*python|experience.*javascript|llm ecosystem|experience.*backend/.test(ctx))
                opt = pickOpt(sel, 'yes');
            if (opt) setVal(sel, opt);
        }
    }""")


async def _click_custom_dropdowns(page: Page):
    """Click-based handler for custom dropdown components (React Select, Select2, etc.)
    that don't respond to querySelectorAll('select')."""
    # Patterns: (text to find near the dropdown, option text to click)
    targets = [
        (re.compile(r"privacy.*notice|privacy.*policy|canonical.*privacy|confirm.*read", re.I),
         re.compile(r"yes|i agree|i confirm|agree", re.I)),
        (re.compile(r"willing.*commit|commit to this|willing.*travel|meet.*person", re.I),
         re.compile(r"yes", re.I)),
        (re.compile(r"which country|country.*work|in which country", re.I),
         re.compile(r"india", re.I)),
        (re.compile(r"gender|ethnicity|race\b|nationality|disability", re.I),
         re.compile(r"prefer not|decline|not to say", re.I)),
        (re.compile(r"require sponsorship|visa sponsorship", re.I),
         re.compile(r"yes", re.I)),
        (re.compile(r"authorized.*work|legally authorized", re.I),
         re.compile(r"no", re.I)),
        (re.compile(r"previously worked|consulted for", re.I),
         re.compile(r"no", re.I)),
    ]

    for label_pat, option_pat in targets:
        try:
            # Find elements that look like custom dropdowns: [role=combobox], [class*=select], etc.
            candidates = await page.query_selector_all(
                '[role="combobox"], [role="listbox"], [class*="select__control"], '
                '[class*="Select__"], [class*="dropdown"], [class*="custom-select"]'
            )
            for el in candidates:
                # Check if this element already has a non-default value
                text = (await el.inner_text()).strip()
                if text and text.lower() not in ("select...", "select", "", "choose..."):
                    continue
                # Get nearby label text to match
                label_text = await page.evaluate("""el => {
                    const texts = [];
                    let node = el.previousElementSibling;
                    while (node) { const t = node.textContent.trim(); if (t.length > 3) texts.push(t); node = node.previousElementSibling; }
                    if (texts.length) return texts[texts.length - 1];
                    const parent = el.parentElement;
                    if (parent) {
                        node = parent.previousElementSibling;
                        while (node) { const t = node.textContent.trim(); if (t.length > 3) return t; node = node.previousElementSibling; }
                    }
                    return el.getAttribute('aria-label') || '';
                }""", el)
                if not label_pat.search(label_text.lower()):
                    continue
                # Click to open
                await el.click()
                await page.wait_for_timeout(400)
                # Find the option
                option_els = await page.query_selector_all('[role="option"], .select__option, [class*="option"]')
                for opt in option_els:
                    opt_text = await opt.inner_text()
                    if option_pat.search(opt_text):
                        await opt.click()
                        await page.wait_for_timeout(200)
                        break
                else:
                    # Close dropdown without selecting
                    await page.keyboard.press("Escape")
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
