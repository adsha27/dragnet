#!/usr/bin/env python3
"""
Find beginner-friendly open issues in target OSS repos.
Outputs ranked issues by contribution potential.

Usage:
    python scripts/find_oss_issues.py
    python scripts/find_oss_issues.py --repo composiohq/composio
    python scripts/find_oss_issues.py --label "good first issue"
    python scripts/find_oss_issues.py --all-tiers

Requires: GITHUB_TOKEN in .env (or set in shell) for higher rate limits.
Without token: 60 req/hour. With token: 5000 req/hour.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

# Tier 1: Primary OSS bet — Composio is hiring and has direct contributor→hire pipeline
# Tier 2: Strong fits — Pipecat (voice AI, WhatsApp+MCP), Firecrawl (RAG, proven hire pipeline)
# Tier 3: Relationship building — Julep (Delhi founders, reachable), Browser-use, SigNoz
OSS_TARGETS = [
    # Tier 1
    {"repo": "composiohq/composio", "tier": 1, "why": "MCP+tools stack match, Ashby ATS, contributor→hire"},
    # Tier 2
    {"repo": "pipecat-ai/pipecat", "tier": 2, "why": "Voice AI, WhatsApp+Sarvam AI match, Python/Go"},
    {"repo": "mendableai/firecrawl", "tier": 2, "why": "Proven contributor→hire (Gergő), RAG/scraping stack"},
    # Tier 3
    {"repo": "Julep-AI/julep", "tier": 3, "why": "Delhi-based founders, Python/TypeScript, reachable"},
    {"repo": "browser-use/browser-use", "tier": 3, "why": "Browser automation, fast-growing, Python"},
    {"repo": "SigNoz/signoz", "tier": 3, "why": "Go+React observability, India-based team, hiring"},
    {"repo": "portkey-ai/gateway", "tier": 3, "why": "LLM gateway, Go codebase, India-adjacent"},
    {"repo": "lancedb/lancedb", "tier": 3, "why": "Vector DB, Rust+Python, growing community"},
]

GOOD_LABELS = [
    "good first issue",
    "good-first-issue",
    "beginner",
    "easy",
    "starter",
    "help wanted",
    "help-wanted",
    "documentation",
    "bug",
    "enhancement",
]

# Issues with these labels are easier entry points
EASY_LABELS = {"good first issue", "good-first-issue", "beginner", "easy", "starter"}


async def fetch_issues(repo: str, token: str | None, labels: list[str]) -> list[dict]:
    """Fetch open issues from a GitHub repo."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    issues = []
    page = 1

    async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as c:
        for label in labels:
            try:
                while True:
                    r = await c.get(
                        f"https://api.github.com/repos/{repo}/issues",
                        params={
                            "state": "open",
                            "labels": label,
                            "per_page": 30,
                            "page": page,
                            "sort": "updated",
                            "direction": "desc",
                        },
                    )
                    if r.status_code == 404:
                        print(f"  repo not found: {repo}", file=sys.stderr)
                        return []
                    if r.status_code == 403:
                        reset = r.headers.get("X-RateLimit-Reset", "unknown")
                        print(f"  Rate limited. Reset at {reset}. Set GITHUB_TOKEN in .env.", file=sys.stderr)
                        return issues
                    r.raise_for_status()
                    batch = r.json()
                    if not batch:
                        break
                    # Filter out pull requests (GitHub API returns both)
                    issues.extend([i for i in batch if "pull_request" not in i])
                    if len(batch) < 30:
                        break
                    page += 1
                    await asyncio.sleep(0.2)
            except Exception as e:
                print(f"  {repo}/{label} failed: {e}", file=sys.stderr)

    # Dedup by issue number
    seen: set[int] = set()
    unique = []
    for issue in issues:
        if issue["number"] not in seen:
            seen.add(issue["number"])
            unique.append(issue)
    return unique


def score_issue(issue: dict, repo_tier: int) -> float:
    """Score an issue by contribution attractiveness."""
    score = 0.0

    # Tier weight (tier 1 = most attractive)
    score += (4 - repo_tier) * 10

    # Label bonuses
    labels = {l["name"].lower() for l in issue.get("labels", [])}
    if labels & EASY_LABELS:
        score += 15
    if "help wanted" in labels or "help-wanted" in labels:
        score += 8
    if "bug" in labels:
        score += 5

    # Comment activity (not zero, not overwhelming)
    comments = issue.get("comments", 0)
    if 0 < comments < 5:
        score += 5  # active but not crowded
    elif comments == 0:
        score += 2  # uncrowded, but less validated

    # Avoid stale issues
    from datetime import datetime, timezone
    updated = issue.get("updated_at", "")
    if updated:
        try:
            dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            days_old = (datetime.now(timezone.utc) - dt).days
            if days_old < 7:
                score += 10
            elif days_old < 30:
                score += 5
            elif days_old > 90:
                score -= 10
        except Exception:
            pass

    # Title length proxy for scope (shorter = simpler)
    title_len = len(issue.get("title", ""))
    if title_len < 60:
        score += 3

    return score


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", help="Single repo to check (e.g. composiohq/composio)")
    parser.add_argument("--label", help="Specific label to filter by")
    parser.add_argument("--all-tiers", action="store_true", help="Show all tiers, not just tier 1+2")
    parser.add_argument("--limit", type=int, default=30, help="Max issues to show")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    # Load GitHub token from env or .env
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("GITHUB_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break

    if not token:
        print("WARNING: No GITHUB_TOKEN found. Rate limited to 60 req/hour.", file=sys.stderr)
        print("Add GITHUB_TOKEN=ghp_... to .env for 5000 req/hour.\n", file=sys.stderr)

    targets = OSS_TARGETS
    if args.repo:
        targets = [{"repo": args.repo, "tier": 1, "why": "manual"}]
    elif not args.all_tiers:
        targets = [t for t in OSS_TARGETS if t["tier"] <= 2]

    labels = [args.label] if args.label else GOOD_LABELS

    all_scored: list[dict] = []

    for target in targets:
        repo = target["repo"]
        tier = target["tier"]
        print(f"Fetching {repo} (Tier {tier})...")
        issues = await fetch_issues(repo, token, labels)
        print(f"  {len(issues)} open issues")
        for issue in issues:
            scored = {
                "repo": repo,
                "tier": tier,
                "why": target["why"],
                "number": issue["number"],
                "title": issue["title"],
                "url": issue["html_url"],
                "labels": [l["name"] for l in issue.get("labels", [])],
                "comments": issue.get("comments", 0),
                "updated_at": issue.get("updated_at", "")[:10],
                "score": score_issue(issue, tier),
            }
            all_scored.append(scored)
        await asyncio.sleep(0.5)

    all_scored.sort(key=lambda x: x["score"], reverse=True)
    top = all_scored[:args.limit]

    if args.json:
        print(json.dumps(top, indent=2))
        return

    print(f"\n{'─'*110}")
    print(f"TOP {len(top)} OSS ISSUES TO CONTRIBUTE TO")
    print(f"{'─'*110}")
    print(f"{'REPO':<30} {'T':>2}  {'#':>5}  {'COMMENTS':>8}  {'UPDATED':>10}  TITLE")
    print(f"{'─'*110}")
    for i in top:
        tier_marker = "★" * (3 - i["tier"] + 1) if i["tier"] <= 3 else ""
        repo_short = i["repo"].split("/")[-1][:28]
        title = i["title"][:55]
        labels_short = ",".join(i["labels"])[:20]
        print(f"{repo_short:<30} {tier_marker:>2}  #{i['number']:<4}  {i['comments']:>8}  {i['updated_at']:>10}  {title}")

    print(f"\n{'─'*110}")
    print("Next steps:")
    print("  1. Pick 2-3 issues from Tier ★★★ (Composio) — go deep, not wide")
    print("  2. Comment on the issue before submitting PR (signal intent, get guidance)")
    print("  3. After 2nd merged PR, reach out to Composio hiring via LinkedIn")

    # Save output
    out = Path("output/oss_issues.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(all_scored, indent=2, default=str))
    print(f"\nFull results saved to {out}")


asyncio.run(main())
