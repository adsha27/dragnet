## Why

The pipeline is fully built — sourcing, eligibility, resume generation, and the executor all exist. The blocker is operational: the 4 category PDFs need regenerating with WeasyPrint, eligible jobs need loading into the DB, and the apply pipeline needs one dry-run pass before going live. Separately, the `uv lock` security finding and `ponytail` evaluation need closing.

## What Changes

- Regenerate all 4 category resumes via WeasyPrint (currently only `global_ai` is fresh)
- Load `eligible_jobs.json` into the Postgres DB via `import_eligible_jobs.py`
- Dry-run the apply pipeline on 5 applications to verify Stagehand/Browserbase form-fill
- Lock all Python dependencies with `uv lock` (supply chain security finding)
- Research and evaluate `ponytail` npm package for potential use in dragnet
- Update `setup.sh` to reflect WeasyPrint dependency (already partially done)

## Capabilities

### New Capabilities

- `dependency-lockfile`: Pin all Python deps to exact versions via `uv.lock`
- `ponytail-eval`: Evaluate whether ponytail npm package is useful in dragnet's pipeline

### Modified Capabilities

- `resume-generation`: WeasyPrint pipeline now canonical; all 4 categories regenerated with fresh LLM tailoring

## Impact

- `scripts/generate_category_resumes.py` — run for all 4 categories
- `scripts/import_eligible_jobs.py` — loads DB
- `scripts/run_apply_pipeline.py` — dry-run then live
- `pyproject.toml` / `uv.lock` — new lockfile committed
- `scripts/setup.sh` — add `uv sync` step
