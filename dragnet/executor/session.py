"""
M4 — Browserbase session management.
Wraps Stagehand for form filling.
Concurrency: 3 sessions max. Per-domain rate limit: 1 app/company/day.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dragnet.config import settings

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(settings.max_concurrent_sessions)
_domain_last_applied: dict[str, datetime] = {}


class BrowserSession:
    """Context manager wrapping a Stagehand browser session."""

    def __init__(self, session_id: str | None = None):
        self._session_id = session_id
        self._stagehand = None
        self._page = None

    async def __aenter__(self):
        await _semaphore.acquire()
        try:
            self._stagehand = await self._create_stagehand()
            self._page = self._stagehand.page
            return self
        except Exception:
            _semaphore.release()
            raise

    async def __aexit__(self, *args):
        try:
            if self._stagehand:
                await self._stagehand.close()
        finally:
            _semaphore.release()

    async def _create_stagehand(self):
        try:
            from stagehand import Stagehand, StagehandConfig
            config = StagehandConfig(
                env="BROWSERBASE",
                browserbase_api_key=settings.browserbase_api_key,
                browserbase_project_id=settings.browserbase_project_id,
                model_api_key=settings.anthropic_api_key,
                model_name=settings.tailoring_model,
                verbose=1,
            )
            sh = Stagehand(config)
            await sh.init()
            return sh
        except ImportError:
            raise ImportError(
                "stagehand package not installed. Run: pip install stagehand\n"
                "See: https://github.com/browserbase/stagehand-python"
            )

    @property
    def page(self):
        return self._page

    async def act(self, instruction: str):
        return await self._stagehand.act(instruction)

    async def extract(self, instruction: str, schema: type | None = None):
        if schema:
            return await self._stagehand.extract(instruction=instruction, schema=schema)
        return await self._stagehand.extract(instruction)

    async def goto(self, url: str):
        await self._page.goto(url)

    async def screenshot(self, path: Path):
        await self._page.screenshot(path=str(path))

    async def upload_file(self, selector: str, file_path: Path):
        """Upload a file via input[type=file] element."""
        file_input = await self._page.query_selector(selector)
        if file_input:
            await file_input.set_input_files(str(file_path))
        else:
            await self._page.set_input_files('input[type="file"]', str(file_path))


def can_apply_to_company(company_slug: str) -> bool:
    last = _domain_last_applied.get(company_slug)
    if last is None:
        return True
    return datetime.now(UTC) - last > timedelta(days=1)


def mark_applied_to_company(company_slug: str):
    _domain_last_applied[company_slug] = datetime.now(UTC)
