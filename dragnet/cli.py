"""
CLI entry point: `dragnet <command>`
"""

import asyncio
import logging

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="dragnet", help="Remote-job acquisition system")
console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@app.command()
def init():
    """Initialize the database."""
    async def _():
        from dragnet.db.connection import init_db
        await init_db()
        console.print("[green]Database initialized.[/green]")
    asyncio.run(_())


@app.command()
def worker():
    """Start the background worker (scheduling all jobs)."""
    from dragnet.worker import run_worker
    asyncio.run(run_worker())


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8080):
    """Start the dashboard web server."""
    import uvicorn
    from dragnet.api.dashboard import app as dashboard_app
    uvicorn.run(dashboard_app, host=host, port=port)


@app.command()
def source():
    """Run sourcing pass now (crawl ATS APIs)."""
    async def _():
        from dragnet.db.connection import SessionLocal, init_db
        await init_db()
        async with SessionLocal() as db:
            from dragnet.sourcing.runner import run_sourcing
            counts = await run_sourcing(db)
            console.print(f"[green]Sourcing complete:[/green] {counts}")
    asyncio.run(_())


@app.command()
def classify():
    """Run classification pass now."""
    async def _():
        from dragnet.db.connection import SessionLocal, init_db
        await init_db()
        async with SessionLocal() as db:
            from dragnet.eligibility.ranker import classify_and_rank_pending
            count = await classify_and_rank_pending(db)
            console.print(f"[green]Classified:[/green] {count} postings")
    asyncio.run(_())


@app.command()
def tailor():
    """Run tailoring pass now."""
    async def _():
        from dragnet.db.connection import SessionLocal, init_db
        await init_db()
        async with SessionLocal() as db:
            from dragnet.executor.queue import run_tailoring_pass
            count = await run_tailoring_pass(db)
            console.print(f"[green]Tailored:[/green] {count} applications")
    asyncio.run(_())


@app.command()
def execute(dry_run: bool = typer.Option(True, "--dry-run/--live", help="Dry run (default) vs live submission")):
    """Run executor pass. Default is dry-run — pass --live to actually submit."""
    async def _():
        from dragnet.db.connection import SessionLocal, init_db
        await init_db()
        async with SessionLocal() as db:
            from dragnet.executor.queue import run_executor_pass
            stats = await run_executor_pass(db, dry_run=dry_run)
            mode = "DRY RUN" if dry_run else "LIVE"
            console.print(f"[green]Executor ({mode}):[/green] {stats}")
    asyncio.run(_())


@app.command()
def stats():
    """Show current funnel stats."""
    async def _():
        from dragnet.db.connection import SessionLocal, init_db
        await init_db()
        async with SessionLocal() as db:
            from dragnet.crm.state import get_funnel_stats
            data = await get_funnel_stats(db)

        table = Table(title="Dragnet Funnel", show_header=True)
        table.add_column("State", style="cyan")
        table.add_column("Count", justify="right", style="bold")

        for state, count in data["funnel"].items():
            table.add_row(state, str(count))

        console.print(table)
        console.print(f"\nSubmitted: {data['total_submitted']}")
        console.print(f"Converted: {data['total_converted']}")
        console.print(f"Rate: {data['conversion_rate']:.1f}%")

        if data["kill_threshold_hit"]:
            console.print(
                "[red bold]KILL THRESHOLD HIT — stop scaling volume, fix positioning[/red bold]"
            )
    asyncio.run(_())


@app.command()
def eval_eligibility():
    """Run M2 eligibility eval against the golden set."""
    async def _():
        import sys
        sys.path.insert(0, "evals/eligibility")
        from evals.eligibility.run_eval import run_eval
        await run_eval()
    asyncio.run(_())


@app.command()
def eval_tailoring():
    """Run M3 tailoring eval (automated firewall check on 10 sample postings)."""
    async def _():
        from evals.tailoring.run_eval import run_automated_eval
        await run_automated_eval()
    asyncio.run(_())


@app.command()
def gmail_auth():
    """Authorize Gmail OAuth. Run once to get token.json."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from dragnet.config import settings

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]
    flow = InstalledAppFlow.from_client_secrets_file(str(settings.gmail_credentials_file), SCOPES)
    creds = flow.run_local_server(port=0)
    settings.gmail_token_file.write_text(creds.to_json())
    console.print(f"[green]Gmail authorized. Token saved to {settings.gmail_token_file}[/green]")


@app.command()
def check_facts():
    """Verify facts.yaml integrity — run before first tailoring pass."""
    from dragnet.tailoring.facts import load_facts
    import yaml

    facts = load_facts()
    unverified = []
    verify_required = []

    for exp in facts.get("experience", []):
        for fact in exp.get("facts", []):
            if not fact.get("verified", False):
                unverified.append(f"[{exp['company']}] {fact['id']}")
            if fact.get("interview_prep_required"):
                verify_required.append(f"[{exp['company']}] {fact['id']}: {fact['claim'][:60]}")

    for proj in facts.get("projects", []):
        for fact in proj.get("facts", []):
            if not fact.get("verified", False):
                unverified.append(f"[project:{proj['name']}] {fact['id']}")

    if unverified:
        console.print(f"[yellow]Unverified facts ({len(unverified)}):[/yellow]")
        for u in unverified:
            console.print(f"  {u}")
    else:
        console.print("[green]All facts verified.[/green]")

    if verify_required:
        console.print(f"\n[red]INTERVIEW PREP REQUIRED before using these in resumes:[/red]")
        for v in verify_required:
            console.print(f"  {v}")


if __name__ == "__main__":
    app()
