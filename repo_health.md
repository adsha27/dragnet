# Repo Health — Phase 1 & Phase 3

## Status: BLOCKED — no real data collected

Every repo below returned the identical error on every attempted call. This is not
a per-repo failure (auth, rate limit, typo, 404) — it is a systemic block in this
session's network layer that intercepts all `https://api.github.com/repos/{owner}/{repo}/...`
traffic before it reaches GitHub, regardless of credentials supplied.

**Verified independently, in this session, before writing this file:**

1. `gh` CLI is not installed (`which gh` → exit 1, `command not found`).
2. A user-supplied GitHub PAT authenticates successfully against non-repo-scoped
   endpoints (`GET https://api.github.com/rate_limit` → `200`, `core.remaining: 4997/5000`),
   proving the token itself is valid.
3. The same token against any `/repos/{owner}/{repo}` path is rejected by the
   environment's egress proxy — not GitHub — with an injected error body (see below),
   `HTTP 403`, on all 13 target repos.
4. `/search/issues`, `/search/repositories`, and `/orgs/{org}` are also rejected by
   the same proxy with a distinct message: `"This GitHub API path is not available:
   sessions are bound to their configured repositories."`
5. The GitHub MCP server tools (`mcp__github__*`), which are separately authenticated,
   independently reject the same repos: `"Access denied: repository ... is not
   configured for this session. Allowed repositories: adsha27/dragnet"`.
6. Attaching any of the 13 repos to this session (`add_repo`) is refused: cross-owner
   attach is rejected as `"cross-tier adds are not supported in v1"`, and push-level
   attach attempts were separately declined by the session's permission classifier.

Because every data point in this task requires a `/repos/{owner}/{repo}/...` call,
**zero real numbers could be collected for any of the 13 repos.** Per the hard rule
("no estimates, no recalled knowledge, no filling gaps... record as ERROR with the
exact error string"), every field below is ERROR, not a guess.

## Rate limit checks

Command: `curl -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" https://api.github.com/rate_limit`

- **Before Phase 1:** HTTP 200 — `core: {"limit":5000,"used":3,"remaining":4997}`
- **After Phase 1 attempts (13 calls):** HTTP 200 — `core: {"limit":5000,"used":3,"remaining":4997}`

`used` did not change across the 13 attempted repo calls, confirming those requests
never reached GitHub's API at all — they were intercepted and answered by the local
proxy.

## Phase 1 table

Command run for every row (identical pattern, repo substituted):
```
curl -sS -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  -w "\nHTTP_CODE:%{http_code}" "https://api.github.com/repos/{owner}/{repo}"
```

| repo | stars | primary_language | language_breakdown | commits_last_30d | open_issues_total | open_issues_labeled_bug | open_bug_issues_updated_last_30d | good_first_issue | help_wanted | external_pr_count | median_days_open_to_merge | max_days_open_to_merge | median_hrs_to_first_maintainer_comment | requires_CLA | has_CONTRIBUTING_md | archived | default_branch |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| modelcontextprotocol/go-sdk | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| modelcontextprotocol/python-sdk | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| modelcontextprotocol/servers | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| BerriAI/litellm | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| BoundaryML/baml | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| explodinggradients/ragas | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| confident-ai/deepeval | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| promptfoo/promptfoo | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| Arize-ai/phoenix | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| openai/evals | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| weaviate/weaviate | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| deepset-ai/haystack | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |
| pgvector/pgvector | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR | ERROR |

## Exact error strings (one per repo, all identical)

All 13 repos returned, verbatim, `HTTP_CODE:403` with body:

```
{"message":"GitHub access to this repository is not enabled for this session. Use add_repo to request access. If add_repo answers that read access is already available and you need GitHub API or write access, call add_repo again with access:\"push\" to attach the repository with credentials.","documentation_url":"https://docs.anthropic.com/en/docs/claude-code/github-actions"}
```

Repos that produced this exact error:
`modelcontextprotocol/go-sdk`, `modelcontextprotocol/python-sdk`, `modelcontextprotocol/servers`,
`BerriAI/litellm`, `BoundaryML/baml`, `explodinggradients/ragas`, `confident-ai/deepeval`,
`promptfoo/promptfoo`, `Arize-ai/phoenix`, `openai/evals`, `weaviate/weaviate`,
`deepset-ai/haystack`, `pgvector/pgvector`.

## Phase 3 — Org context

Not attempted beyond the confirmatory test below, since Phase 1 already established
the systemic block and Phase 3 requires the same `/orgs/{org}` path family.

Command: `curl -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" https://api.github.com/orgs/pgvector`

Result: `HTTP 403`
```
{"message":"This GitHub API path is not available: sessions are bound to their configured repositories. Use repository-scoped endpoints (repos/{owner}/{repo}/...).","documentation_url":"https://docs.anthropic.com/en/docs/claude-code/github-actions"}
```

All 13 repos' owning orgs: `public_members_count`, `location`, `blog`, `created_at`,
`public_repos_count` = ERROR (same cause).

## What would unblock this

This session (bound to `adsha27/dragnet`) enforces an egress allowlist at the proxy
layer that only permits `/repos/{owner}/{repo}/...` calls for repos attached to the
session, and refuses to attach repos owned by a different account/org
(`"cross-tier adds are not supported in v1"`). No credential, tool, or retry from
inside this session can cross that boundary. Running this task would require a
session/environment not scoped this way (e.g., initiated fresh against one of the
target repos, or with an unrestricted network policy).

## Time spent

Wall time on verification + attempted collection: well under the 20-minute budget
(~3 minutes). Stopped once the block was confirmed systemic rather than burning
the full budget on 13 known-identical failures.
