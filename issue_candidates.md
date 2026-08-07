# Issue Candidates — Phase 2

## Status: NOT RUN — no eligible repos

Phase 2 only runs for repos where Phase 1 established
`external_pr_count >= 3 AND median_days_open_to_merge <= 21`.

Phase 1 (see `./repo_health.md`) collected **zero real values** for any of the 13
repos: every `/repos/{owner}/{repo}/...` call was intercepted by this session's
egress proxy and returned `HTTP 403` before reaching GitHub, regardless of the
GitHub PAT supplied. This was independently reproduced via raw `curl` with a valid
token, the GitHub MCP server tools, and confirmed again after an MCP server
reconnect mid-task (`mcp__github__list_commits` on `pgvector/pgvector` →
`"Access denied: repository ... is not configured for this session. Allowed
repositories: adsha27/dragnet"`).

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
