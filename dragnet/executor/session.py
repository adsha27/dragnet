"""
Browser session management using local Playwright (no Browserbase required).
Concurrency: 3 sessions max. Per-domain rate limit: 1 app/company/day.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dragnet.config import settings

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(settings.max_concurrent_sessions)
_domain_last_applied: dict[str, datetime] = {}


class BrowserSession:
    """Context manager wrapping a local Playwright browser session."""

    def __init__(self, session_id: str | None = None):
        self._playwright = None
        self._browser = None
        self._page = None

    async def __aenter__(self):
        await _semaphore.acquire()
        try:
            await self._start()
            return self
        except Exception:
            _semaphore.release()
            raise

    async def __aexit__(self, *args):
        try:
            await self._stop()
        finally:
            _semaphore.release()

    async def _start(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        ctx = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        self._page = await ctx.new_page()
        await self._page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

    async def _stop(self):
        for obj, method in [
            (self._page, "close"),
            (self._browser, "close"),
            (self._playwright, "stop"),
        ]:
            if obj:
                try:
                    await getattr(obj, method)()
                except Exception:
                    pass

    @property
    def page(self):
        return self._page

    async def goto(self, url: str):
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def screenshot(self, path: Path):
        if self._page:
            await self._page.screenshot(path=str(path))

    async def upload_file(self, selector: str, file_path: Path):
        if self._page:
            el = await self._page.query_selector(selector)
            target = el or await self._page.query_selector('input[type="file"]')
            if target:
                await target.set_input_files(str(file_path))


def can_apply_to_company(company_slug: str) -> bool:
    last = _domain_last_applied.get(company_slug)
    if last is None:
        return True
    return datetime.now(timezone.utc) - last > timedelta(days=1)


def mark_applied_to_company(company_slug: str):
    _domain_last_applied[company_slug] = datetime.now(timezone.utc)
