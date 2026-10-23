# Changelog

## 0.1.3 - Candidate

- Release the catalog-reference human formatter under a new package version.
- Preserve catalog hashes, unsupported amount and comparison flags, billing, conditions and provider retrieval dates in CLI and MCP text.
- Keep structured JSON, authentication, shared quotas and public-data semantics unchanged.

## 0.1.2 - 2026-10-23

- Explicit pricing coverage request and account-owned status methods and CLI commands.
- Consent and target validation before HTTP; shared API metering and immutable request IDs retained.
- Request status text includes the domain, hints, reason, revision and published snapshot.

## 0.1.1 - Candidate

- Optional exact competitor product filter in the Python client and CLI.
- Preserves omitted-filter requests, response coverage and shared weighted quota.
- Identifies the client and request User-Agent as 0.1.1.

## 0.1.0 - Early access

- REST client and CLI for source-backed snapshots, product search/history,
  sources, reviewed records, scenario comparison and account usage.
- Competitor-pricing reads preserve one explicit seed, qualified retained
  relationships, bounded snapshot selections and partial or missing coverage.
- Private atomic key configuration, bounded responses/timeouts, refused
  redirects, structured errors and stable JSON output.
- Separate compatible local MCP gateway; pilot access is issued independently
  of package installation. No hosted OAuth, PyPI or Registry publication claimed.
