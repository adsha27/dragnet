# Aditya Sharma — Master Profile (Resume Source Document)

Purpose: single source of truth for generating role-specific resumes (backend, AI engineer, full-stack, etc.). Everything here is drawn from verified sources: the RWF repository git history, live production database pulls, benchmark artifacts, and the public GitHub profile. Nothing in this document is invented. When a number is soft or unverified, it is labelled as such. Do not put labelled-soft numbers on a resume without confirming them first.

Last updated: 11 June 2026.

---

## 0. CONTACT & IDENTITY

- Name: Aditya Sharma
- Email: aditya0327sharma@gmail.com
- Phone: +91 98293 68698
- GitHub: github.com/adsha27
- Location: India (Jaipur / Delhi NCR). Open to remote.
- Current title: Member of Technical Staff, Backend — Right Walk Foundation (Delhi), Feb 2026–present.

---

## 1. ONE-LINE POSITIONING (pick per stream)

- Backend: Backend engineer building production LLM/agent systems in Go and Python — MCP tools, RAG, load benchmarking, and observability for real users.
- AI engineer: AI engineer shipping production agentic systems — 46 MCP tools, RAG pipelines, multilingual conversational bots serving a live pilot, with eval and observability infrastructure.
- Full-stack (weaker — see §8): Backend-leaning engineer with production Go/Python systems and some TypeScript/JS and Unity/C# project work.

---

## 2. VERIFIED PROFESSIONAL EXPERIENCE

### Right Walk Foundation — Member of Technical Staff, Backend
Delhi · Feb 2026 – Present · On-site

Context: RWF builds public-service WhatsApp bots that help citizens access government schemes. Two production bots: NAPS (apprenticeship registration) and RTE (right-to-education school admissions). Stack: Go (backend, agent loop, Chatwoot/WhatsApp integration) + Python (MCP tool layer / microportal).

VERIFIED ENGINEERING FOOTPRINT (from git history of the private repo):
- 172 commits authored (Feb 3 – Jun 10, 2026). #2 contributor by commit count.
- ~88,636 lines added, ~9,339 deleted, across 582 file-level changes. [NOTE: LOC includes RAG corpora and PDF/chunking assets — do NOT cite raw LOC on a resume; it reads as padding. Use commit count or scope instead.]
- 145 commits across core product surfaces; 65 commits on highest-value areas (MCP registration, backend serving/campaigns, prompt/BAML surfaces, RAG assets).
- Touched 33 distinct test/eval artifacts.

Commit distribution by area (verified):
- microportal/naps: 116 change-events, 24 files (NAPS MCP tools)
- chatwhat/cmd: 87 change-events, 59 files (CLI / ops / server)
- chatwhat/baml_src: 74 change-events, 8 files (prompts)
- chatwhat/backend: 50 change-events, 23 files (serving, campaigns)
- microportal/rtegj: 49 change-events, 23 files (RTE MCP tools)
- chatwhat/msger: 19 change-events, 8 files (WhatsApp/messaging)

PRODUCTION SYSTEMS BUILT/EXTENDED (verified):
- 2 production bot services (/naps-bot, /rtegj-bot) wired in the Go server.
- 6 active backend HTTP routes (health, channel-dump, 2 bot endpoints, 2 campaign endpoints).
- Messaging stack across WhatsApp + Chatwoot, with campaign sync (Chatwoot conversation creation + WhatsApp delivery + DB note logging).
- 46 production MCP tools total: 29 NAPS + 17 RTE.
  - NAPS tools: registration OTP, resend activation, login OTP + login, email activation, eKYC, bank-detail checks, profile read/update, qualification CRUD, semantic suggestion/search, apprenticeship search, application submit + retrieve, complaints, CSAT.
  - RTE tools: policy RAG, application status, district/block discovery, WhatsApp location tutorial, Form A / Form B fill, school preference CRUD + confirmation, document status/upload/delete/confirm.

PERFORMANCE / OPTIMIZATION WORK (verified, with caveats):
- Concurrency ceiling fix: identified that the LLM orchestration layer (BAML) bounded effective concurrency at ~50 simultaneous calls. After removing it, a 1,000-user benchmark (6 sequential calls, 1s stubbed LLM latency) dropped from 115s to its ~6s theoretical floor, leaving the pipeline LLM-bound.
  - [INTERVIEW PREP REQUIRED: be able to name the exact serialization mechanism — shared client behind a lock, bounded worker pool, or per-host HTTP connection limit — and point to the saved benchmark run. The 115s→6s number must be reproducible before it goes on a resume sent widely.]
- DB connection-pool fix: a pool was being recreated per request instead of reusing the existing pool; fixed to reuse. Reduced allocations on the conversation-registration path (RegisterConv ~7%, main bench path ~8% in the captured profiles). [NOTE: aggregate CPU/memory in the pooled profile was mixed, not uniformly better — frame as "fixed a pool-recreation bug, reducing allocations on the hot conversation path," not "50% faster overall."]
- Profiling capability: profiled the Go backend under load with pprof (CPU, allocation, and execution-trace profiles) to compare resource cost across model and configuration variants (incl. DeepSeek trials). [Frame as a capability — "I can profile and reason about Go performance under load" — not as a single optimization win.]

VERIFICATION / EVAL / OBSERVABILITY (verified):
- Test surface: 63 test files, 148 named test cases, 6 benchmarks.
- Benchmarks include: a NAPS AI agent benchmark, 3 backend chat benchmarks, a multi-user conversation benchmark, and a Chatwoot stress harness parameterized for 1,000 users / 100 active users-per-second / 20s. Backend benchmarks guard up to 300 concurrent load units.
- RTE long-chat eval pack: 8 scenario files across 5 languages (English, Gujarati, Hindi, Malayalam, Marathi).
- Observability layer (built/contributed): per-call token usage (input/output tokens, agent name, duration), MCP tool analytics (tool name, status, error type/message, start/finish time), success/error analytics on every tool invocation, and middleware injecting conversation_id / trace_id / span_id into tool-call context.

DATA / RAG ASSETS (verified):
- NAPS RAG corpus: 12 JSONL corpora, 377 total chunks/records, from 13 source policy PDFs.
- RTE school dataset: 9,722 rows (the searchable school universe for the RTE flow).

LIVE PRODUCTION USAGE (verified from local Postgres pulls — this is a PILOT, describe it as such):
- NAPS chat DB: 1,170 stored chat events/messages; 156 distinct conversations; 72 conversations with ≥1 user message; first message 2026-03-18, last 2026-06-08.
  - Message breakdown: 427 user, 509 AI-agent, 130 tool, 82 system, 13 system-reachout. Avg 7.5 messages/conversation, max 36.
- MCP tool analytics: 563 total tool calls; 448 successful; 115 errored; overall success rate 79.6%; 29 distinct tools invoked; avg tool duration 2,560 ms; window 2026-03-13 to 2026-06-10.
  - Top live tools: search_apprenticeship_opportunities (143 calls, 80% success), post_onboarding_data (139, 98%), query_rte_policy_documents (58, 100%), naps_documentation_rag (31, 100%), check_application_status (22, 0% — failing in prod), get_login_otp (21, 81%), fill_form_A_for_application (21, 5% — failing in prod).
  - [INTERVIEW ASSET: the failing tools (check_application_status 0/22, fill_form_A 1/20) are your single best "I own production failure" story. Do NOT hide them. "I built the instrumentation that surfaces these failure rates" is a senior-level line.]
- Honesty boundary on "users": app-side hard facts are 156 conversations, 72 user-active, 1 credential-persisted user, 2 OTP-attempt emails, 1 feedback row. Local Chatwoot production DB was empty, so total unique WhatsApp users across all production history is NOT measurable from available data. Never claim a unique-user count beyond what is listed here.

WORK BEYOND THE OBVIOUS BULLETS (verified themes from commit messages):
- Campaign/reachout production plumbing (not just chatbot features).
- Productionization/parity work ("bring into production," "backfill production parity," "runtime support," "A/B testing readiness").
- Eval architecture + model bakeoff workflow.
- CLI/developer tooling for bot simulation/testing (local Chatwoot testing, no-reset CLI).
- RAG ingestion/chunking/doc-refresh pipeline maintenance for official NAPS policy material.

### Mercury Digital — Technical Project Manager
Jaipur · Aug 2025 – Jan 2026 · On-site
- Drove technical delivery across a pricing system, catalogue architecture, an AI chatbot workflow, and Android + iOS apps. Aligned developers, content, and marketing on scope and timelines across parallel tracks.
- [Stream note: this is a PM role, not an engineering role. On a backend/AI resume compress to 1–2 lines. On a generalist/PM-adjacent resume it can expand. Do not inflate into an engineering role.]

### Custard — Co-Founder
Jaipur · Jun 2023 – Nov 2023
- Built a platform for local interest-based communities (Python, SQL, MongoDB). Owned backend architecture and product direction; ran early-user outreach across India.

---

## 3. VERIFIED PROJECTS (from GitHub: github.com/adsha27, 9 repos)

Use these selectively per stream. The ML/CV notebooks are student-grade but are the only public AI artifacts, so they matter for the AI-engineer stream's "breadth" section. Confirm each repo's current state and add a one-line live-link or description before listing.

- govRAG (Python) — RAG over government documents. Closest public artifact to the RWF production work. STRONGEST public repo for backend/AI streams. [ACTION: confirm it has a README + is runnable; this is the one to polish first.]
- MaarSaab (TypeScript, WebApp v0.1) — exists and is started (contradicts "unbuilt"; it's early-stage, not absent). Only meaningful TypeScript/frontend-adjacent artifact. [Decide: finish to a demoable state or leave off. Currently too thin to anchor a frontend claim.]
- Amazon-Price-Prediction-from-Unstructured-Data (Jupyter) — ML on unstructured data; relevant for AI/ML breadth. 1 star.
- house-price-prediction (Jupyter) — classic regression project; entry-level ML signal. 1 star.
- Pose-Estimation-with-MediaPipe (Jupyter) — CV project; shows range into vision.
- NewsWave-Project (JavaScript) — the only frontend-ish public artifact; thin. Not enough to anchor a frontend resume alone.
- Interactive Interior Visualization System (Unity, C#) — NOT on GitHub but real freelance delivery: a Unity tool for a real-estate builder letting clients preview interiors pre-construction with editable furniture/paint/lighting and real-time day/night. Shows C# + 3D/graphics range. Good differentiator on backend/AI resumes precisely because it's different.
- [9 repos total per profile; 3 not surfaced publicly — inventory them and add any with substance.]

---

## 4. SKILLS INVENTORY (grouped; pull per stream)

Verified-in-production (safe to lead with):
- Languages: Go, Python, SQL. Also: TypeScript/JavaScript (project-level), C# (Unity project).
- Backend: FastAPI, REST APIs, PostgreSQL, pgvector, MongoDB.
- AI / Agents: LLM orchestration, RAG pipelines, FastMCP / MCP tool design, prompt engineering, evals, multilingual agent systems.
- Infra/Tooling: Docker, Linux, Git, AWS, pprof profiling.
- Observability: token-usage instrumentation, tool analytics, trace/span context.

Project-level / supporting (claim only where relevant, don't overstate):
- ML/CV: scikit-learn-style regression, MediaPipe pose estimation, working with unstructured data (Jupyter).
- Frontend: JavaScript, some TypeScript (NewsWave, MaarSaab). NOT a strong frontend profile — see §8.
- 3D/Graphics: Unity, C#.

---

## 5. EDUCATION
- B.Tech, Computer Science — Jaipur Engineering College and Research Center, 2025. CGPA 7.1/10.

---

## 6. THE NUMBERS, IN ONE PLACE (for quick resume assembly)
- 172 commits, #2 contributor, RWF production repo (4 months)
- 46 production MCP tools (29 NAPS + 17 RTE)
- 2 production bots, 6 backend routes
- 5 languages supported, evaluated via 8-scenario eval pack
- 63 test files, 148 test cases, 6 benchmarks; 1,000-user / 100-aups stress harness
- 156 conversations, 1,170 messages, 72 user-active (live pilot)
- 563 tool calls, 79.6% success rate, 29 tools invoked live
- 9,722-school dataset; 377-chunk RAG corpus from 13 policy PDFs
- 115s → 6s on the 1,000-user concurrency benchmark (BAML removal) [reproducible-before-use]

---

## 7. PER-STREAM ASSEMBLY GUIDE

### Backend engineer (STRONGEST — target this first)
Lead with: Go/Python production systems, 46 MCP tools, concurrency/pool optimization, benchmarking + pprof, observability, Postgres/pgvector. Live pilot numbers as proof of real deployment. This is the most defensible resume you can produce today.

### AI engineer (STRONG — co-primary)
Lead with: 46 MCP tools, RAG pipelines (govRAG + RWF corpus), multilingual conversational agents, eval architecture (8-scenario bakeoff), token/tool observability, the 79.6% success-rate + failing-tool ownership story. Add ML/CV notebooks as breadth. govRAG is the public anchor — polish it.

### Full-stack / generalist (MODERATE — needs one frontend build)
Honest today: backend + light TS/JS (NewsWave, MaarSaab) + Unity/C#. Can credibly claim "full-stack leaning backend" only if you finish MaarSaab to a demoable front end. Until then, target "backend" not "full-stack."

### Frontend engineer (WEAK — do not target yet)
Current public evidence: one thin JS project + an early TS web app. A frontend resume now would be mostly unbacked claims, which fails the moment someone asks to see work. If you want this stream, the prerequisite is 1–2 real shipped front ends (finish MaarSaab, build one more). Flagged honestly rather than padded.

### Technical PM / founding engineer (VIABLE — different framing)
Combine Mercury (TPM across pricing/catalogue/AI-chatbot/mobile) + Custard (co-founder, owned architecture + product) + RWF (ships production systems end to end). Frame as "engineer who can own product and delivery," strong for early-stage startups.

---