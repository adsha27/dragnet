## 1. Config and normalization foundation

- [x] 1.1 Add `applicant_linkedin` to `dragnet/config.py` (reads `APPLICANT_LINKEDIN` env var, default empty string)
- [x] 1.2 Add `APPLICANT_LINKEDIN` to `.env.example`
- [x] 1.3 Create `dragnet/tailoring/unicode_normalize.py` with `normalize(text: str) -> str` — em-dash, smart quotes, ellipsis, bullet, NBSP, zero-width chars → ASCII
- [x] 1.4 Add a unit test for `normalize()` covering each substitution (no mocks needed)

## 2. Tailoring pass rewrite

- [x] 2.1 Update `run_tailoring_pass` in `dragnet/executor/queue.py` to resolve category PDF from `output/category_resumes/<category>.pdf` instead of calling `generate_resume()`
- [x] 2.2 Add liveness check in tailoring pass: skip `linkedin.com` URLs, call `check_liveness()` for others, set state to `ineligible` on dead postings
- [x] 2.3 Log WARNING when category PDF not found (posting left in `eligible` state)

## 3. Greenhouse adapter fixes

- [x] 3.1 Replace LinkedIn skip comment with `settings.applicant_linkedin` fill (skip field if empty)
- [x] 3.2 Wrap all `session.act()` string arguments with `normalize()` from `unicode_normalize.py`

## 4. Pipeline orchestrator script

- [x] 4.1 Create `scripts/run_apply_pipeline.py` with steps: (1) run tailoring pass, (2) run terminal approval gate, (3) run executor pass
- [x] 4.2 Implement terminal approval gate: print company/title/url/category, accept `y/n/a/q` input
- [x] 4.3 Add `--dry-run` flag that passes through to executor pass
- [x] 4.4 Add `--limit N` flag to cap how many applications are processed per run
- [x] 4.5 Print summary at end: tailored N, approved M, submitted K, rejected R

## 5. Smoke test

- [x] 5.1 Run `python scripts/run_apply_pipeline.py --dry-run --limit 1` against one eligible job from DB; verify preflight screenshot is saved and state is NOT advanced to `submitted`
