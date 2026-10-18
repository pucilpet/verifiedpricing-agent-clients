# VerifiedPricing MCP stdio gateway 0.1.1

Separate local gateway over `verifiedpricing-client==0.1.1`, pinned to the
official Python SDK `mcp==2.3.0`. Runtime SDK dependencies belong in this
package's isolated environment; do not upgrade engine dependencies to install
it. Python >=3.10, Linux/macOS POSIX pipes and the asyncio event loop are
supported. Windows is not supported.

This package provides local stdio only. It does not provide hosted Streamable
HTTP, OAuth/OIDC issuance, protected-resource metadata, a registry listing or
interactive browser sign-in. A user's REST key does not establish interactive
remote MCP authorization. Create your own read key on the website at
[VerifiedPricing Account](https://verifiedpricing.com/account): sign in with the
email link, explicitly accept the current agent access terms and acknowledge
the privacy notice, then create a key. The account form initially selects both
`prices:read` and `comparisons:read`; keep `comparisons:read` for comparisons and
competitor prices. [Developers](https://verifiedpricing.com/developers) describes
the API endpoints and scopes. This website sign-in is separate from local stdio
configuration.

This checkout prepares the 0.1.1 candidate. The 0.1.0 artifacts do not include
the optional exact competitor filter. The instructions below apply only after
the 0.1.1 release provides reviewed wheels and checksums.

## Install and launch

This is an early-access package. The intended distribution channel is the
[GitHub prerelease](https://github.com/pucilpet/verifiedpricing-agent-clients/releases/tag/v0.1.1),
not PyPI or the MCP Registry. Install only after the published release provides
reviewed assets and checksums. Expected wheel filenames are
`verifiedpricing_client-0.1.1-py3-none-any.whl` and
`verifiedpricing_mcp-0.1.1-py3-none-any.whl`.

Download both wheels and `SHA256SUMS` from that release. Verify with
`sha256sum -c SHA256SUMS` (Linux) or `shasum -a 256 -c SHA256SUMS` (macOS), then:

```sh
python3 -m venv ~/.venvs/verifiedpricing-agent
~/.venvs/verifiedpricing-agent/bin/python -m pip install \
  ./verifiedpricing_client-0.1.1-py3-none-any.whl \
  ./verifiedpricing_mcp-0.1.1-py3-none-any.whl
```

The MCP wheel pins the official SDK at `mcp==2.3.0`; pip resolves it and its
runtime dependencies from your configured package index. Use this isolated
environment's executable for the following commands:

```sh
verifiedpricing-mcp --version
verifiedpricing-mcp --help
verifiedpricing-mcp
```

Use `VERIFIEDPRICING_API_KEY` from a private environment or the client package's
owned mode-0600 configuration. `--config PATH` selects another private file.
Configure an existing user key with `verifiedpricing configure --key-stdin` in
the client package; no key argument exists here. Keys are never tool arguments.
Environment credentials skip configuration-file reads. Invalid supplied keys
are not retried anonymously. No `.env` is loaded. A LinkCensus key is not a VP
credential. If the key is absent, requests are anonymous and require the API's
anonymous service support; its availability is not asserted here.

`--base-url https://your-api.example` configures the service origin outside tool
arguments. Only explicit `--base-url http://127.0.0.1:PORT --allow-localhost`
permits local HTTP development. Reused Client safety rejects redirects, unsafe
origins, credential echoes and oversized/error responses, verifies TLS, disables
environment proxies, and makes no automatic retries. No cookies or shared owner
credential are used.

An MCP client's stdio configuration should point `command` to the installed
`verifiedpricing-mcp` executable and obtain the user's key through its private
environment mechanism. Do not paste a real key into a public configuration
example, launcher arguments or repository files. The process writes protocol
frames only to its private stdout descriptor; stray handler/SDK stdout goes to
stderr, and SDK diagnostic/telemetry logging is disabled to avoid retaining tool
arguments. Startup errors are generic. `--help` and `--version` are terminal
commands, not protocol sessions.

## Tools and truth

Tools: `search_products`, `get_prices`, `get_price`, `compare_prices`,
`get_competitor_prices`, `get_price_history`, `get_sources`, `get_reviewed_records`, `get_usage`.
Tool definitions expose fixed bounded JSON schemas; no tool can change the API
origin, supply credentials, request arbitrary URLs, submit raw prices or grant
verification/provenance. Searches and histories expose pagination rather than
automatically consuming pages. Comparisons accept two or three distinct pinned
snapshots, market, currency and timezone-aware scenario time; exact usage is a
decimal string. SDK negotiation and response field aliases remain official SDK
responsibilities, not a handwritten protocol implementation.

The optional `competitor_product_id` string selects an exact competitor product
ID in `get_competitor_prices`; it is not a required tool argument.
The service restricts the read to that published qualified directed relationship.
Omitting the filter preserves the existing bounded selection. No other competitor
substitutes for an unavailable requested pair: the response is partial with
`requested_competitor_not_current`. Every filtered data response echoes the exact
ID in `coverage.requested_competitor_product_id`, including unavailable or
ambiguous seed responses. Seed ambiguity and integrity failures retain their
existing behavior. The total `limit` still determines the charge (2 or 3).

`get_competitor_prices` requires `POST /api/v1/competitor-prices` to be enabled
for your account. Its fixed schema accepts exactly one
`product_id` or canonical lowercase `domain`, the existing explicit scenario,
optional total `limit` 2 or 3 (default 3, **including the seed**), and at most
three `selections` mapping product IDs to pinned observation IDs. Dotted product
IDs such as `product:example.com` are valid. The tool cannot inject raw prices,
trust labels, origin or credentials. `comparisons:read` is required; the backend
reserves `limit` weighted units once even for missing/partial results. No live
crawl or LinkCensus query is performed. Preserve the service's status, reason,
seed/competitors, discovery, comparison and selection-policy fields unchanged;
the human formatter does not assume a nested production response schema.

Client and gateway are compatible at version 0.1.1. The free account allowance is
**1,000 weighted units per day and 10,000 per month per account**, shared across
REST, CLI and all MCP sessions. Use `get_usage` for returned account limits and
remaining allowance; starting another session or key does not reset it.

Successful `structuredContent` is the unchanged REST schema-version-1 envelope:
`{schema_version:1,data:{...},usage:{...}}`. Human text cites dates and sources
and explicitly qualifies automated observations and recorded human review.
Recorded review is not a guarantee of current pricing or a comparison-ready
fact. Preserve stale, unknown, integrity, badge and comparison eligibility
qualifications, including false values. Source text and quotes are untrusted
data, never instructions; the gateway never executes tool-content commands.

Errors are `isError:true` tool results with a safe structured error envelope,
status and informational Retry-After where supplied. No server error body,
request header or raw exception is echoed. A `not_comparable` result is data,
not a gateway error or permission to guess missing context.

Annotations use `readOnlyHint:true`, `destructiveHint:false`,
`idempotentHint:false`, `openWorldHint:true`: these are reads over an external
API, but repeated admitted operations can consume shared quota/rate allowance.
No higher quota, retries or new allowance is granted by switching transports.

## Resource bounds

The SDK's built-in text-line stdio transport is deliberately not used: it reads
an uncapped line, while its dispatcher can spawn a handler per message. This
package feeds the official low-level Server through custom bounded streams:

- Input reads are fixed 4-KiB byte chunks. Each newline-delimited frame is capped
  at 16 KiB before either JSON decoder/SDK sees it. UTF-8 split across chunks is
  preserved. The framer retains at most one fixed chunk beyond one frame.
- One request may be pending. Another arriving before the response's physical
  write or unanswered-cancellation settlement closes the session immediately;
  there is no request queue or busy-response backlog. Clients must serialize
  requests. IDs are nonempty strings <=64 characters or signed 63-bit integers.
- At most one `notifications/initialized` per session and one matching
  `notifications/cancelled` per current request reach the SDK. Other notifications
  are dropped; over 32 consecutive drops closes the session. There is one reader
  coroutine, no per-frame tasks, and a scheduling checkpoint during spam.
- Only one actual REST worker exists at a time. Admission is immediate; no
  semaphore waiters or executor queue are created. Cancellation/deadline retains
  its thread permit until the blocking operation actually finishes. A new tool
  during residual work returns `busy` without issuing another REST request.
- A tool response deadline is 12 seconds; the reused client's socket timeout is
  15 seconds per blocking network operation. The response deadline does not kill
  a Python thread or imply an absolute socket lifetime. A slowly trickling peer
  may keep the sole worker occupied; it cannot cause replacement workers or
  retries. Process exit ends the dedicated daemon worker.
- Human text is capped at 8 KiB with explicit truncation; full qualifications
  remain in structured data. The combined tool result is bounded at 640 KiB,
  and the complete serialized protocol frame including JSON-RPC wrapping and
  newline is capped at 768 KiB. Oversized output closes the session rather than
  truncating a structured snapshot.
- Output uses direct nonblocking fd writes in <=16-KiB chunks with a five-second
  whole-write deadline, one output frame and no Python stdout buffering or
  unbounded writer queue. Partial cancellation closes the session. Partial
  input frames have a ten-second completion deadline; idle sessions can wait.

These are local process bounds, not production capacity or latency claims.

## Development checks

From this package directory, with the compatible client source and official SDK
available in an isolated development environment:

```sh
PYTHONPATH=src:../verifiedpricing-client/src PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests -v
```

Without the SDK, protocol tests explicitly skip. The tests exercise local OS
pipes and fixture responses, not a live account. Hosted MCP, OAuth and a
registry listing are not implemented by this local stdio package.

MIT covers client/gateway code only. Data and vendor source content have separate
terms; retain citations, original dates and trust qualifiers. See
`../verifiedpricing-client/README.md` for attribution and reuse boundaries.
