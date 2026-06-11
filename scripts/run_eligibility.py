#!/usr/bin/env python3
"""
Run eligibility filter over scraped jobs.
No database needed — reads output/india_jobs.json, writes output/eligible_jobs.json.

Usage:
    python scripts/run_eligibility.py
    python scripts/run_eligibility.py --limit 100     # test on first N jobs
    python scripts/run_eligibility.py --fast-only     # pre-filter only, no LLM
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fast-only", action="store_true")
    parser.add_argument("--input", default="output/india_jobs.json")
    parser.add_argument("--output", default="output/eligible_jobs.json")
    args = parser.parse_args()

    from dragnet.eligibility.classifier import pre_filter, classify_posting

    jobs = json.loads(Path(args.input).read_text())
    if args.limit:
        jobs = jobs[:args.limit]

    print(f"Loaded {len(jobs)} jobs from {args.input}")

    pre_passed: list[dict] = []
    pre_rejected = 0
    for job in jobs:
        title = job.get("title", "")
        text = job.get("content_text", "")
        ok, reason = pre_filter(title, text)
        if ok:
            pre_passed.append(job)
        else:
            pre_rejected += 1

    print(f"Pre-filter: {len(pre_passed)} passed, {pre_rejected} rejected")

    if args.fast_only:
        _save_and_print(pre_passed, args.output, "pre-filter")
        return

    # LLM classification in batches of 5 concurrent
    eligible: list[dict] = []
    ineligible_reasons: dict[str, int] = {}
    errors = 0
    batch_size = 5

    print(f"\nRunning Qwen3 classifier on {len(pre_passed)} jobs...")
    for i in range(0, len(pre_passed), batch_size):
        batch = pre_passed[i:i + batch_size]
        tasks = [
            classify_posting(
                company=j.get("company_name", ""),
                title=j.get("title", ""),
                text=j.get("content_text", ""),
            )
            for j in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for job, result in zip(batch, results):
            if isinstance(result, Exception):
                errors += 1
                continue
            if result.eligible:
                job["_classification"] = {
                    "market": result.market,
                    "city": result.city,
                    "seniority": result.seniority,
                    "comp_min_lpa": result.comp_min_lpa,
                    "comp_max_lpa": result.comp_max_lpa,
                    "comp_min_usd_month": result.comp_min_usd_month,
                    "comp_max_usd_month": result.comp_max_usd_month,
                    "stack_tags": result.stack_tags,
                    "eor_signals": result.eor_signals,
                    "reasoning": result.reasoning,
                }
                eligible.append(job)
            else:
                r = result.reject_reason or "unknown"
                ineligible_reasons[r] = ineligible_reasons.get(r, 0) + 1

        done = min(i + batch_size, len(pre_passed))
        pct = done / len(pre_passed) * 100
        print(f"  {done}/{len(pre_passed)} ({pct:.0f}%) — {len(eligible)} eligible so far", end="\r")

    print()
    _save_and_print(eligible, args.output, "LLM classifier")
    print(f"\nRejection reasons:")
    for reason, count in sorted(ineligible_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:<20} {count}")
    if errors:
        print(f"  errors: {errors}")


def _save_and_print(jobs: list[dict], output_path: str, stage: str):
    Path(output_path).write_text(json.dumps(jobs, indent=2, default=str))
    print(f"\n{'─'*70}")
    print(f"ELIGIBLE after {stage}: {len(jobs)}")
    print(f"{'─'*70}")
    print(f"{'TITLE':<40} {'COMPANY':<25} {'LOCATION'}")
    print(f"{'─'*70}")
    for j in sorted(jobs, key=lambda x: x.get("company_name", ""))[:40]:
        title = (j.get("title") or "")[:38]
        company = (j.get("company_name") or "")[:23]
        location = (j.get("location") or "")[:20]
        cls = j.get("_classification", {})
        comp = ""
        if cls.get("comp_min_lpa"):
            comp = f"₹{cls['comp_min_lpa']}-{cls.get('comp_max_lpa', '?')} LPA"
        elif cls.get("comp_min_usd_month"):
            comp = f"${cls['comp_min_usd_month']}/mo"
        print(f"{title:<40} {company:<25} {location:<22} {comp}")
    if len(jobs) > 40:
        print(f"  ... and {len(jobs)-40} more")
    print(f"\nSaved to {output_path}")


asyncio.run(main())
