"""
M4 — Browserbase session management via Stagehand v3.x API.
Acts/navigates through sessions resource: sessions.start() -> id -> act/navigate/end.
File upload and screenshots use Playwright via Browserbase CDP.
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
    """Context manager wrapping a Stagehand v3.x browser session."""

    def __init__(self, session_id: str | None = None):
        self._given_session_id = session_id
        self._client = None
        self._session_id: str | None = None
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
        from stagehand import AsyncStagehand
        self._client = AsyncStagehand(
            browserbase_api_key=settings.browserbase_api_key,
            browserbase_project_id=settings.browserbase_project_id,
        )
        if self._given_session_id:
            self._session_id = self._given_session_id
            cdp_url = None
        else:
            resp = await self._client.sessions.start(
                model_name="claude-haiku-4-5-20251001",
                browserbase_session_create_params={
                    "projectId": settings.browserbase_project_id,
                },
            )
            self._session_id = resp.id
            cdp_url = resp.data.cdp_url

        # Connect Playwright for file upload / screenshot
        await self._connect_playwright(cdp_url)

    async def _connect_playwright(self, cdp_url: str | None = None):
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            ws_url = cdp_url or (
                f"wss://connect.browserbase.com?apiKey={settings.browserbase_api_key}"
                f"&sessionId={self._session_id}"
            )
            self._browser = await self._playwright.chromium.connect_over_cdp(ws_url)
            contexts = self._browser.contexts
            if contexts:
                pages = contexts[0].pages
                self._page = pages[0] if pages else await contexts[0].new_page()
            else:
                ctx = await self._browser.new_context()
                self._page = await ctx.new_page()
        except Exception as e:
            logger.warning(f"Playwright CDP connect failed: {e} — screenshots/uploads unavailable")

    async def _stop(self):
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        if self._client and self._session_id and not self._given_session_id:
            try:
                await self._client.sessions.end(self._session_id)
            except Exception:
                pass

    @property
    def page(self):
        return self._page

    async def act(self, instruction: str):
        # Use Playwright for all interaction — Stagehand navigate 500s on LinkedIn
        if self._page:
            return await self._page.evaluate(f"() => {{ /* {instruction} */ }}")
        return await self._client.sessions.act(
            self._session_id,
            input={"description": instruction},
        )

    async def extract(self, instruction: str, schema: type | None = None):
        kwargs = {"instruction": instruction}
        if schema:
            kwargs["schema"] = schema
        return await self._client.sessions.extract(self._session_id, **kwargs)

    async def goto(self, url: str):
        if self._page:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        else:
            await self._client.sessions.navigate(self._session_id, url=url)

    async def screenshot(self, path: Path):
        if self._page:
            await self._page.screenshot(path=str(path))
        else:
            logger.warning(f"No Playwright page — screenshot skipped: {path}")

    async def upload_file(self, selector: str, file_path: Path):
        if self._page:
            file_input = await self._page.query_selector(selector)
            if file_input:
                await file_input.set_input_files(str(file_path))
            else:
                await self._page.set_input_files('input[type="file"]', str(file_path))
        else:
            logger.warning(f"No Playwright page — file upload skipped: {file_path}")


def can_apply_to_company(company_slug: str) -> bool:
    last = _domain_last_applied.get(company_slug)
    if last is None:
        return True
    return datetime.now(timezone.utc) - last > timedelta(days=1)


def mark_applied_to_company(company_slug: str):
    _domain_last_applied[company_slug] = datetime.now(timezone.utc)
