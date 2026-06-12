"""
M5 — CRM state machine.
Manages application lifecycle transitions and ghost detection.
"""

import logging
from datetime import datetime, timedelta, timezone
UTC = timezone.utc

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.config import settings
from dragnet.db.models import Application, ApplicationState, StateTransition

logger = logging.getLogger(__name__)


async def transition(
    app: Application,
    to_state: ApplicationState,
    trigger: str,
    db: AsyncSession,
):
    """Record a state transition and update application."""
    if app.state == to_state:
        return

    transition = StateTransition(
        application_id=app.id,
        from_state=app.state,
        to_state=to_state,
        trigger=trigger,
    )
    app.state = to_state
    app.last_state_at = datetime.now(UTC)
    db.add(transition)


async def check_ghost_timeouts(db: AsyncSession) -> int:
    """
    Find submitted applications with no reply after GHOST_TIMEOUT_DAYS.
    Transition: submitted → ghosted. Send one follow-up email if not yet sent.
    """
    cutoff = datetime.now(UTC) - timedelta(days=settings.ghost_timeout_days)

    result = await db.execute(
        select(Application).where(
            Application.state == ApplicationState.submitted,
            Application.submitted_at < cutoff,
            Application.follow_up_sent_at.is_(None),
        )
    )
    apps = result.scalars().all()

    ghosted_count = 0
    for app in apps:
        await transition(app, ApplicationState.ghosted, "ghost_timeout", db)
        ghosted_count += 1
        logger.info(f"Application {app.id} ghosted (no reply in {settings.ghost_timeout_days} days)")

    await db.commit()
    return ghosted_count


async def get_funnel_stats(db: AsyncSession) -> dict:
    """Return current funnel counts for the dashboard."""
    result = await db.execute(select(Application))
    apps = result.scalars().all()

    counts: dict[str, int] = {}
    for state in ApplicationState:
        counts[state.value] = 0

    for app in apps:
        counts[app.state.value] = counts.get(app.state.value, 0) + 1

    total_submitted = sum(
        counts.get(s, 0)
        for s in ["submitted", "screened", "interviewing", "offer", "rejected", "ghosted"]
    )
    total_converted = counts.get("screened", 0) + counts.get("interviewing", 0) + counts.get("offer", 0)

    conversion_rate = (total_converted / total_submitted * 100) if total_submitted > 0 else 0.0

    return {
        "funnel": counts,
        "total_submitted": total_submitted,
        "total_converted": total_converted,
        "conversion_rate": round(conversion_rate, 2),
        "kill_threshold_hit": conversion_rate < 1.0 and total_submitted >= 100,
    }
