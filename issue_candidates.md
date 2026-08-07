# Issue Candidates — Phase 2

## Status: NOT RUN — no eligible repos

Phase 2 only runs for repos where Phase 1 established
`external_pr_count >= 3 AND median_days_open_to_merge <= 21`.

`external_pr_count` and `median_days_open_to_merge` both require pull-request data,
which only exists via the GitHub REST/GraphQL API (`/repos/{owner}/{repo}/pulls`,
`author_association`). That API remains blocked for these 13 repos in this session
(see `./repo_health.md` for the full proof: raw `curl` with a valid PAT, the GitHub
MCP tools, and add_repo attach all independently rejected every one of them). A
separate channel — the git wire protocol — did recover 3 unrelated fields
(`default_branch`, `commits_last_30d`, `has_CONTRIBUTING_md`, see repo_health.md),
but PR/issue metadata isn't exposed over that protocol at all, so it can't help here.

`external_pr_count` and `median_days_open_to_merge` are therefore `ERROR`, not a
number, for all 13 repos — the qualification condition cannot be evaluated, so no
repo can be honestly marked eligible. Per the hard rule against filling gaps with
estimates, no issues are listed below.

| repo | external_pr_count | median_days_open_to_merge | eligible | reason |
|---|---|---|---|---|
| modelcontextprotocol/go-sdk | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| modelcontextprotocol/python-sdk | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| modelcontextprotocol/servers | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| BerriAI/litellm | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| BoundaryML/baml | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| explodinggradients/ragas | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| confident-ai/deepeval | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| promptfoo/promptfoo | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| Arize-ai/phoenix | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| openai/evals | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| weaviate/weaviate | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| deepset-ai/haystack | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |
| pgvector/pgvector | ERROR | ERROR | unknown | Phase 1 blocked, see repo_health.md |

No issues collected.
