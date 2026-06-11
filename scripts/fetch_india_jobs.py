#!/usr/bin/env python3
"""
Standalone job fetcher — LinkedIn, Naukri, Remotive, Himalayas, YC Work at a Startup.
No database required. Prints results to stdout and writes to output/india_jobs.json.

Usage:
    python scripts/fetch_india_jobs.py
    python scripts/fetch_india_jobs.py --pages 3
    python scripts/fetch_india_jobs.py --linkedin-only
    python scripts/fetch_india_jobs.py --source linkedin,himalayas,remotive
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=2, help="LinkedIn pages per query")
    parser.add_argument("--linkedin-only", action="store_true")
    parser.add_argument(
        "--source",
        default="all",
        help="Comma-separated sources: linkedin,naukri,remotive,himalayas,workatastartup,remoteok,hn",
    )
    args = parser.parse_args()

    if args.linkedin_only:
        sources = {"linkedin"}
    elif args.source == "all":
        sources = {"linkedin", "naukri", "remotive", "himalayas", "workatastartup", "remoteok", "hn"}
    else:
        sources = set(args.source.split(","))

    from dragnet.sourcing import linkedin, naukri, remotive, himalayas, workatastartup, remoteok, hn

    all_jobs: list[dict] = []

    if "linkedin" in sources:
        print("── LinkedIn ─────────────────────────────────")
        li_jobs = await linkedin.fetch_postings(max_pages=args.pages)
        print(f"  {len(li_jobs)} jobs")
        all_jobs.extend(li_jobs)

    if "himalayas" in sources:
        print("── Himalayas ────────────────────────────────")
        h_jobs = await himalayas.fetch_postings()
        print(f"  {len(h_jobs)} jobs")
        all_jobs.extend(h_jobs)

    if "remotive" in sources:
        print("── Remotive ─────────────────────────────────")
        r_jobs = await remotive.fetch_postings()
        print(f"  {len(r_jobs)} jobs")
        all_jobs.extend(r_jobs)

    if "workatastartup" in sources:
        print("── YC Work at a Startup ─────────────────────")
        y_jobs = await workatastartup.fetch_postings()
        print(f"  {len(y_jobs)} jobs")
        all_jobs.extend(y_jobs)

    if "remoteok" in sources:
        print("── RemoteOK ─────────────────────────────────")
        ro_jobs = await remoteok.fetch_postings()
        print(f"  {len(ro_jobs)} jobs")
        all_jobs.extend(ro_jobs)

    if "hn" in sources:
        print("── HN Who is Hiring ─────────────────────────")
        try:
            hn_jobs = await hn.fetch_postings(month_lookback=2)
            print(f"  {len(hn_jobs)} jobs")
            all_jobs.extend(hn_jobs)
        except Exception as e:
            print(f"  HN skipped: {e}")

    if "naukri" in sources:
        print("── Naukri ───────────────────────────────────")
        try:
            n_jobs = await naukri.fetch_postings()
            print(f"  {len(n_jobs)} jobs")
            all_jobs.extend(n_jobs)
        except Exception as e:
            print(f"  Naukri skipped: {e}")

    # Dedup across sources by dedup_hash
    seen: set[str] = set()
    unique_jobs: list[dict] = []
    for j in all_jobs:
        h = j.get("dedup_hash", "")
        if h and h not in seen:
            seen.add(h)
            unique_jobs.append(j)

    # Source breakdown
    by_source: dict[str, int] = {}
    for j in unique_jobs:
        src = j.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    print(f"\n{'─' * 80}")
    print("SOURCE BREAKDOWN:")
    for src, count in sorted(by_source.items()):
        print(f"  {src:<20} {count}")
    print(f"{'─' * 80}")
    print(f"TOTAL UNIQUE: {len(unique_jobs)}")
    print(f"{'─' * 80}\n")

    # Top 50 preview
    print(f"{'TITLE':<40} {'COMPANY':<25} {'SRC':<15} {'LOCATION'}")
    print(f"{'─' * 100}")
    for j in sorted(unique_jobs, key=lambda x: x.get("company_name", ""))[:50]:
        title = (j.get("title") or "")[:38]
        company = (j.get("company_name") or "")[:23]
        location = (j.get("location") or "")[:18]
        source = (j.get("source") or "")[:13]
        print(f"{title:<40} {company:<25} {source:<15} {location}")

    if len(unique_jobs) > 50:
        print(f"  ... and {len(unique_jobs) - 50} more")

    out = Path("output/india_jobs.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(unique_jobs, indent=2, default=str))
    print(f"\nSaved {len(unique_jobs)} jobs to {out}")


asyncio.run(main())
