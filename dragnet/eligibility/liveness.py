"""
Posting liveness check — verify a job URL still shows an open posting
before spending tokens on tailoring or submitting an application.

Fast HTTP check: if the page returns 404, 410, or contains known
"position filled" / "no longer accepting" strings, mark it dead.
No browser needed for most ATS providers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_DEAD_PHRASES = [
    "position has been filled",
    "no longer accepting",
    "job is no longer available",
    "this job has expired",
    "posting has been closed",
    "this position is no longer",
    "applications are no longer",
    "this listing has been removed",
    "job listing is closed",
    "vacancy has been closed",
    "position is closed",
    "role has been filled",
    "we are no longer",
]

_TIMEOUT = httpx.Timeout(10.0)


@dataclass
class LivenessResult:
    live: bool
    reason: str


async def check_liveness(url: str) -> LivenessResult:
    """
    Returns LivenessResult(live=True) if the posting appears active.
    Returns live=False with reason if the posting looks dead.
    On network error, returns live=True (give benefit of the doubt).
    """
    if not url:
        return LivenessResult(live=True, reason="no url")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; dragnet/1.0)"},
        ) as client:
            resp = await client.get(url)
    except Exception as e:
        logger.debug(f"Liveness check network error for {url}: {e}")
        return LivenessResult(live=True, reason=f"network_error: {e}")

    if resp.status_code in (404, 410):
        return LivenessResult(live=False, reason=f"http_{resp.status_code}")

    if resp.status_code >= 400:
        return LivenessResult(live=True, reason=f"http_{resp.status_code}_skip")

    body_lower = resp.text.lower()
    for phrase in _DEAD_PHRASES:
        if phrase in body_lower:
            return LivenessResult(live=False, reason=f"phrase: {phrase}")

    return LivenessResult(live=True, reason="ok")
