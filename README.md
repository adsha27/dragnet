# dragnet

Automated job acquisition pipeline. Finds backend/AI engineering roles, scores eligibility, tailors resumes, and submits applications.

```
source -> eligibility -> resume -> apply -> human gate
```

## What it does

1. **Source** -- pulls jobs from LinkedIn search, Greenhouse, Lever, and Ashby APIs (68 companies, ~4,500 jobs per run)
2. **Filter** -- keyword pre-filter drops non-tech roles; Qwen3:14b (local, via Ollama) classifies remaining ~400 for YoE, comp, and remote eligibility
3. **Resume** -- WeasyPrint renders one of 4 category PDFs (`india_backend`, `india_ai`, `global_backend`, `global_ai`) from a Jinja2 template + facts.yaml
4. **Apply** -- Stagehand/Browserbase fills forms on Greenhouse, Lever, and LinkedIn Easy Apply
5. **Human gate** -- first 50 submissions require explicit approval; after that, 10% sampling

## Stack

- Python 3.13, uv
- Qwen3:14b via Ollama (local LLM -- no API key required)
- PostgreSQL 16 (Docker)
- Playwright / Stagehand / Browserbase (browser automation)
- WeasyPrint 69 (HTML to PDF)
- FastAPI (internal API for human gate)

## Setup

```bash
# Prerequisites: Docker, Ollama, uv
ollama pull qwen3:14b
docker run -d --name dragnet-db -e POSTGRES_PASSWORD=dragnet -p 5432:5432 postgres:16

git clone https://github.com/adsha27/dragnet
cd dragnet
cp .env.example .env   # fill in credentials
uv sync
uv run dragnet init    # create DB tables
```

## Running

```bash
# 1. Fetch jobs from all ATS sources
uv run python scripts/fetch_ats_jobs.py

# 2. Run eligibility filter (uses Ollama -- takes several hours on CPU)
uv run python scripts/run_eligibility.py \
  --input output/ats_jobs.json \
  --output output/eligible_ats_jobs.json \
  --batch-size 3

# 3. Import to DB
uv run python scripts/import_eligible_jobs.py --input output/eligible_ats_jobs.json

# 4. Generate category resumes
uv run python scripts/generate_category_resumes.py

# 5. Dry-run apply pipeline (no real submissions)
uv run python scripts/run_apply_pipeline.py --dry-run --limit 5

# 6. Go live
uv run python scripts/run_apply_pipeline.py --limit 20
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | yes | Postgres connection string |
| `BROWSERBASE_API_KEY` | yes | For Stagehand browser sessions |
| `LINKEDIN_EMAIL` | yes | LinkedIn account for Easy Apply |
| `LINKEDIN_PASSWORD` | yes | LinkedIn account password |
| `APPLICANT_NAME` | yes | Full name for form fills |
| `APPLICANT_EMAIL` | yes | Contact email for applications |
| `APPLICANT_PHONE` | yes | Phone number for form fills |

## Job sources

**Greenhouse (API):** Anthropic, Databricks, Scale AI, Coreweave, Stripe, Datadog, Cloudflare, GitLab, Elastic, Canonical, MongoDB, Figma, Vercel, Postman, and more.

**Lever (API):** Meesho, Remote.com, Retool, Brex, Ramp, WorkOS, Doppler.

**Ashby (API):** Perplexity, Groq, Mistral, Cohere, Together AI, Modal, Baseten, W&B, LangChain, ElevenLabs, Warp, Zed, Posthog, Linear, Supabase, Composio, Sarvam AI, and more.

**LinkedIn:** Search-based sourcing with Easy Apply detection. Most roles funnel here.

## Safety

- Human approval gate on first 50 submissions
- Dry-run mode for all adapters (no real submissions)
- Facts firewall: rejects resume HTML if any number is not in `facts.yaml`
- Prompt injection defense: JD content wrapped in `<jd>` XML tags at all LLM call sites
- No external API keys for LLM -- fully local via Ollama

## Current state

650 eligible jobs in DB across Databricks, Anthropic, Canonical, Stripe, Datadog, Scale AI, and LinkedIn sourcing. Apply pipeline ready pending Browserbase credentials.
