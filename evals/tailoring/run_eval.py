"""
Tailoring quality eval. Run on 10 sample postings after M3.

Two checks:
1. AUTOMATED: Facts firewall — every number in generated resume exists in facts.yaml
2. HUMAN: Quality rubric — you evaluate each resume before scaling

Pass gate: firewall 100% + human ≥9/10 "would submit" + 0 invented claims.
"""

import asyncio
import json
import re
from pathlib import Path

SAMPLE_POSTINGS_DIR = Path(__file__).parent / "sample_postings"
RESULTS_FILE = Path(__file__).parent / "results.json"

SAMPLE_POSTINGS = [
    {
        "id": "tp_001",
        "company": "Trigger.dev",
        "title": "Backend Engineer",
        "text": "We are building the best platform for background jobs. Looking for a backend engineer with Go or Python, experience with distributed systems, async queues, and cloud infrastructure. Experience with LLMs or AI agents is a strong plus.",
        "difficulty": "strong_fit",
    },
    {
        "id": "tp_002",
        "company": "Posthog",
        "title": "Software Engineer, Data Pipeline",
        "text": "PostHog is looking for a software engineer to work on our data ingestion pipeline. Python preferred. Experience with observability, telemetry, and high-throughput systems. PostgreSQL and Redis experience helpful.",
        "difficulty": "strong_fit",
    },
    {
        "id": "tp_003",
        "company": "Cal.com",
        "title": "Backend Engineer, Integrations",
        "text": "We're building the open-source scheduling infrastructure. Need backend engineers who can build reliable integrations with third-party APIs, webhooks, and event-driven systems. TypeScript/Node preferred but open to Python.",
        "difficulty": "strong_fit",
    },
    {
        "id": "tp_004",
        "company": "Encore.dev",
        "title": "Software Engineer",
        "text": "Backend engineer to work on our developer platform. Experience with cloud infrastructure (AWS), Go is a plus. We value engineers who think about reliability and developer experience.",
        "difficulty": "medium_fit",
    },
    {
        "id": "tp_005",
        "company": "Tinybird",
        "title": "Software Engineer, API",
        "text": "Python backend engineer. Experience with real-time data APIs, high throughput, low latency. Some experience with SQL databases. Bonus: ClickHouse or columnar databases.",
        "difficulty": "medium_fit",
    },
    {
        "id": "tp_006",
        "company": "Neon",
        "title": "Software Engineer, Client Libraries",
        "text": "We're building the serverless Postgres platform. Looking for engineers who can build SDKs and client libraries. Experience with PostgreSQL internals, TypeScript, Python. Strong writing skills.",
        "difficulty": "medium_fit",
    },
    {
        "id": "tp_007",
        "company": "Temporal",
        "title": "Software Engineer, Workflow Engine",
        "text": "Temporal is looking for engineers to work on our workflow engine. Go is the primary language. Deep distributed systems knowledge required. Experience with durable execution, state machines, and fault tolerance.",
        "difficulty": "medium_fit",
    },
    {
        "id": "tp_008",
        "company": "Oxide Computer",
        "title": "Software Engineer, Embedded Rust",
        "text": "Rust systems programmer. Deep embedded systems experience, firmware development, bare metal programming. Experience with microcontrollers, hardware bring-up, and low-level debugging.",
        "difficulty": "weak_fit",
    },
    {
        "id": "tp_009",
        "company": "Modal Labs",
        "title": "ML Platform Engineer",
        "text": "We're building infrastructure for running ML models at scale. CUDA programming, GPU optimization, deep learning frameworks (PyTorch). Experience with distributed training.",
        "difficulty": "weak_fit",
    },
    {
        "id": "tp_010",
        "company": "Hashnode",
        "title": "Backend Engineer, Content Platform",
        "text": "Node.js / TypeScript backend engineer. GraphQL API design, content management systems, blogging infrastructure. Experience with Next.js is a plus.",
        "difficulty": "weak_fit",
    },
]


async def run_automated_eval():
    """Runs the facts firewall check on generated resumes. Cannot be gamed."""
    from dragnet.tailoring.firewall import check_resume_against_facts
    from dragnet.tailoring.resume import generate_resume
    from dragnet.tailoring.answers import generate_answers

    results = []
    firewall_failures = 0

    for posting in SAMPLE_POSTINGS:
        print(f"\n[{posting['id']}] Generating for {posting['company']} ({posting['difficulty']})...")

        resume_path, resume_html = await generate_resume(posting)
        answers = await generate_answers(posting)

        firewall_result = check_resume_against_facts(resume_html)

        result = {
            "id": posting["id"],
            "company": posting["company"],
            "difficulty": posting["difficulty"],
            "resume_path": str(resume_path),
            "firewall_passed": firewall_result.passed,
            "firewall_violations": firewall_result.violations,
            "answers": answers,
            "human_review": {
                "would_submit": None,
                "any_invented_claim": None,
                "why_us_specific": None,
                "notes": "",
            },
        }

        if not firewall_result.passed:
            firewall_failures += 1
            print(f"  FIREWALL FAIL: {firewall_result.violations}")
        else:
            print(f"  Firewall: OK")

        results.append(result)

    print(f"\n{'='*60}")
    print(f"AUTOMATED CHECK: {len(SAMPLE_POSTINGS) - firewall_failures}/{len(SAMPLE_POSTINGS)} passed firewall")
    if firewall_failures > 0:
        print("FAIL — fix hallucinated numbers before human review")
    else:
        print("Firewall: PASS — proceed to human review")
        print("\nOpen each PDF and fill in human_review fields in results.json")

    RESULTS_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {RESULTS_FILE}")
    return results


def score_human_review():
    """Score after you've filled in human_review fields in results.json."""
    if not RESULTS_FILE.exists():
        print("Run automated eval first")
        return

    results = json.loads(RESULTS_FILE.read_text())
    would_submit = sum(1 for r in results if r["human_review"].get("would_submit") is True)
    invented = sum(1 for r in results if r["human_review"].get("any_invented_claim") is True)
    generic = sum(1 for r in results if r["human_review"].get("why_us_specific") == "generic")
    unreviewed = sum(1 for r in results if r["human_review"].get("would_submit") is None)

    print(f"\n{'='*60}")
    print("HUMAN REVIEW RESULTS")
    print(f"{'='*60}")
    print(f"Would submit:        {would_submit}/{len(results)}  (target: ≥9)")
    print(f"Invented claims:     {invented}  (target: 0)")
    print(f"Generic 'why us':    {generic}  (target: ≤2)")
    print(f"Unreviewed:          {unreviewed}")

    if unreviewed > 0:
        print(f"\nPlease review all {unreviewed} remaining resumes first")
        return

    PASS = would_submit >= 9 and invented == 0
    print(f"\n{'PASS ✓' if PASS else 'FAIL ✗ — fix tailoring before scaling'}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "score":
        score_human_review()
    else:
        asyncio.run(run_automated_eval())
