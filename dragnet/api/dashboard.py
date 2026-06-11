"""
M5 — Dashboard: single-page FastAPI app showing funnel metrics.
Read-only. This is where kill-thresholds get read.
"""

import logging

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dragnet.crm.state import get_funnel_stats
from dragnet.db.connection import get_session
from dragnet.db.models import Application, ApplicationState, Posting

logger = logging.getLogger(__name__)
app = FastAPI(title="Dragnet Dashboard")


@app.get("/", response_class=HTMLResponse)
async def dashboard(db: AsyncSession = Depends(get_session)):
    stats = await get_funnel_stats(db)

    recent_result = await db.execute(
        select(Application)
        .order_by(Application.last_state_at.desc())
        .limit(20)
    )
    recent = recent_result.scalars().all()

    top_eligible_result = await db.execute(
        select(Posting)
        .where(Posting.india_eligible.in_(["yes", "likely_yes"]))
        .order_by(Posting.rank_score.desc())
        .limit(10)
    )
    top_eligible = top_eligible_result.scalars().all()

    kill_warning = ""
    if stats["kill_threshold_hit"]:
        kill_warning = """
        <div style="background:#ff4444;color:white;padding:16px;margin:16px 0;border-radius:4px;font-weight:bold;">
            ⚠ KILL THRESHOLD HIT: conversion rate {:.1f}% after {} submissions.<br>
            Stop scaling volume. Bottleneck is positioning/resume, not quantity.
        </div>""".format(stats["conversion_rate"], stats["total_submitted"])

    funnel_rows = ""
    funnel = stats["funnel"]
    state_order = [
        "discovered", "eligible", "ineligible", "tailored",
        "human_review", "human_rejected", "submitted",
        "screened", "interviewing", "offer", "rejected", "ghosted"
    ]
    for state in state_order:
        count = funnel.get(state, 0)
        bar_width = min(count * 5, 200)
        funnel_rows += f"""
        <tr>
            <td style="padding:6px 12px;font-family:monospace">{state}</td>
            <td style="padding:6px 12px;text-align:right;font-weight:bold">{count}</td>
            <td style="padding:6px 12px">
                <div style="background:#333;height:12px;width:{bar_width}px;display:inline-block"></div>
            </td>
        </tr>"""

    recent_rows = ""
    for a in recent:
        company = a.posting.company.name if (a.posting and a.posting.company) else "—"
        title = a.posting.title if a.posting else "—"
        recent_rows += f"""
        <tr>
            <td style="padding:4px 12px">{company}</td>
            <td style="padding:4px 12px">{title[:50]}</td>
            <td style="padding:4px 12px;font-family:monospace">{a.state.value}</td>
            <td style="padding:4px 12px;color:#666">{a.last_state_at.strftime('%Y-%m-%d') if a.last_state_at else '—'}</td>
        </tr>"""

    top_rows = ""
    for p in top_eligible:
        company = p.company.name if p.company else "—"
        comp_range = f"${p.comp_min//1000}k–${p.comp_max//1000}k" if p.comp_min and p.comp_max else "—"
        top_rows += f"""
        <tr>
            <td style="padding:4px 12px">{company}</td>
            <td style="padding:4px 12px">{p.title[:50]}</td>
            <td style="padding:4px 12px">{p.india_eligible.value if p.india_eligible else '—'}</td>
            <td style="padding:4px 12px">{comp_range}</td>
            <td style="padding:4px 12px;font-weight:bold">{p.rank_score:.1f if p.rank_score else '—'}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<title>Dragnet</title>
<meta charset="utf-8">
<meta http-equiv="refresh" content="60">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #111; margin: 0; padding: 0; }}
  .container {{ max-width: 960px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px 0; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  .card {{ background: white; border-radius: 6px; padding: 16px 0; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
  .card h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: #666; margin: 0 12px 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  tr:nth-child(even) {{ background: #fafafa; }}
  .metric {{ display: inline-block; margin: 0 24px 0 0; }}
  .metric .value {{ font-size: 28px; font-weight: bold; }}
  .metric .label {{ font-size: 12px; color: #666; }}
  .metrics {{ padding: 0 16px 8px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Dragnet</h1>
  <div class="meta">Auto-refreshes every 60s · {stats['total_submitted']} submitted · {stats['conversion_rate']:.1f}% conversion (target ≥3%)</div>

  {kill_warning}

  <div class="card">
    <h2>Funnel</h2>
    <div class="metrics">
      <div class="metric"><div class="value">{stats['total_submitted']}</div><div class="label">Submitted</div></div>
      <div class="metric"><div class="value">{stats['total_converted']}</div><div class="label">Converted (screened+)</div></div>
      <div class="metric"><div class="value">{stats['conversion_rate']:.1f}%</div><div class="label">Rate (kill @ &lt;1% at 100+)</div></div>
    </div>
    <table>{funnel_rows}</table>
  </div>

  <div class="card">
    <h2>Top Eligible Postings (unqueued)</h2>
    <table>
      <tr style="color:#666;font-size:12px">
        <th style="text-align:left;padding:4px 12px">Company</th>
        <th style="text-align:left;padding:4px 12px">Title</th>
        <th style="text-align:left;padding:4px 12px">Eligible</th>
        <th style="text-align:left;padding:4px 12px">Comp</th>
        <th style="text-align:left;padding:4px 12px">Score</th>
      </tr>
      {top_rows}
    </table>
  </div>

  <div class="card">
    <h2>Recent Activity</h2>
    <table>
      <tr style="color:#666;font-size:12px">
        <th style="text-align:left;padding:4px 12px">Company</th>
        <th style="text-align:left;padding:4px 12px">Role</th>
        <th style="text-align:left;padding:4px 12px">State</th>
        <th style="text-align:left;padding:4px 12px">Updated</th>
      </tr>
      {recent_rows}
    </table>
  </div>
</div>
</body>
</html>"""

    return HTMLResponse(content=html)


@app.get("/api/stats")
async def api_stats(db: AsyncSession = Depends(get_session)):
    return await get_funnel_stats(db)


@app.post("/api/approve/{application_id}")
async def approve_application(application_id: int, db: AsyncSession = Depends(get_session)):
    """Approve a human-review application for submission."""
    from dragnet.crm.state import transition
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        return {"error": "not found"}
    if app.state != ApplicationState.human_review:
        return {"error": f"state is {app.state.value}, expected human_review"}
    await transition(app, ApplicationState.tailored, "human_approved", db)
    await db.commit()
    return {"status": "approved", "application_id": application_id}


@app.post("/api/reject/{application_id}")
async def reject_application(application_id: int, db: AsyncSession = Depends(get_session)):
    """Reject a human-review application (don't submit)."""
    from dragnet.crm.state import transition
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        return {"error": "not found"}
    await transition(app, ApplicationState.human_rejected, "human_rejected", db)
    await db.commit()
    return {"status": "rejected", "application_id": application_id}
