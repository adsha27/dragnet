# ATS Job Board Sites

Reference for all ATS platforms dragnet can source from. Columns: public API, URL pattern, auth required, status.

## Tier 1 — Public API, No Auth (implemented)

| Platform | API Endpoint | Web URL | Notes |
|----------|-------------|---------|-------|
| **Greenhouse** | `boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` | `boards.greenhouse.io/{slug}` | Most popular for YC/VC-backed companies |
| **Lever** | `api.lever.co/v0/postings/{slug}?mode=json` | `jobs.lever.co/{slug}` | Common at growth-stage startups |
| **Ashby** | `api.ashbyhq.com/posting-api/job-board/{slug}` | `jobs.ashbyhq.com/{slug}` | Popular with AI-native companies |
| **Recruitee** | `{slug}.recruitee.com/api/offers/` | `{slug}.recruitee.com` | European mid-market; implemented |

## Tier 2 — Public API, No Auth (not yet implemented)

| Platform | API Endpoint | Web URL | Notes |
|----------|-------------|---------|-------|
| **SmartRecruiters** | `api.smartrecruiters.com/v1/companies/{slug}/postings` | `jobs.smartrecruiters.com/{slug}` | Enterprise; companies like Bosch, LVMH |
| **Workable** | `apply.workable.com/api/v3/accounts/{slug}/jobs` | `apply.workable.com/{slug}` | Popular with European startups |
| **JazzHR** | `api.resumatorapi.com/v1/jobs` (requires API key per company) | `apply.jazz.co/{slug}` | API key per company, not practical |
| **BreezyHR** | `api.breezy.hr/v3/company/{slug}/positions?state=published` | `{slug}.breezy.hr` | No auth needed for public positions |

## Tier 3 — Web Scrape Only (no public API)

| Platform | Web URL | Notes |
|----------|---------|-------|
| **Workday** | `{company}.wd1.myworkdayjobs.com/en-US/{board}` | Instance-based URL per company; JavaScript-heavy; anti-scrape |
| **iCIMS** | `careers.icims.com/{company}/jobs` | Enterprise ATS; no public API |
| **BambooHR** | `{company}.bamboohr.com/jobs/` | API authenticated; web only for public boards |
| **Jobvite** | `jobs.jobvite.com/{slug}` | No public API documented |
| **Taleo** | `{company}.taleo.net/careersection` | Oracle-acquired; enterprise only |
| **SuccessFactors** | `{company}.successfactors.com` | SAP; enterprise only |

## Special Sources

| Source | URL | Notes |
|--------|-----|-------|
| **Stripe Apps Directory** | `docs.stripe.com/directory` | Lists companies that built Stripe apps (B2B SaaS). JavaScript SPA — needs browser scrape. Good for finding employer companies. |
| **YC Companies** | `ycombinator.com/companies` | Filterable by batch/vertical. Companies link to their ATS. |
| **LinkedIn** | `linkedin.com/jobs` | Easy Apply detection; sourced separately via LinkedIn sourcing module |

## Google Dork Patterns (manual sourcing)

Use these to find jobs on specific ATS platforms:

```
site:jobs.ashbyhq.com backend engineer OR "software engineer" India OR remote
site:boards.greenhouse.io backend engineer India OR remote
site:jobs.lever.co software engineer India OR remote
site:apply.workable.com backend engineer India OR remote
site:jobs.smartrecruiters.com software engineer India OR remote
```

## Finding New Company Slugs

- Greenhouse: `curl https://boards-api.greenhouse.io/v1/boards/{slug}/jobs` — 200 means valid
- Lever: `curl https://api.lever.co/v0/postings/{slug}` — non-empty array means valid
- Ashby: `curl https://api.ashbyhq.com/posting-api/job-board/{slug}` — check for `jobPostings` key
- Recruitee: `curl https://{slug}.recruitee.com/api/offers/` — check for `offers` key

## ATS Detection by URL Pattern

Given a job URL, identify the ATS:
- `boards.greenhouse.io` or `grnh.se` → Greenhouse
- `jobs.lever.co` or `lever.co` → Lever
- `jobs.ashbyhq.com` or `ashbyhq.com` → Ashby
- `*.recruitee.com` → Recruitee
- `*.myworkdayjobs.com` or `wd1.myworkdayjobs.com` → Workday
- `jobs.smartrecruiters.com` or `careers.smartrecruiters.com` → SmartRecruiters
- `careers.icims.com` → iCIMS
- `jobs.jobvite.com` or `jobs.jobvite.com` → Jobvite
- `bamboohr.com/jobs` → BambooHR
- `apply.workable.com` or `*.workable.com` → Workable
- `apply.jazz.co` → JazzHR/Jazz
