# MCP integration

`verifiedpricing-mcp==0.1.1` is a separate local stdio gateway over
`verifiedpricing-client==0.1.1` and the official `mcp==2.3.0` SDK. The client stays
stdlib-only. See the [gateway README](../verifiedpricing-mcp/README.md) for
release assets, installation, launch configuration and process limits.

Get your own read key at [VerifiedPricing Account](https://verifiedpricing.com/account).
Sign in with the email link, explicitly accept the current agent access terms
and acknowledge the privacy notice, then create a key. The account form initially
selects `prices:read` and `comparisons:read`; keep `comparisons:read` for comparisons
and competitor prices. See [Developers](https://verifiedpricing.com/developers)
for endpoint and scope details.

Configure the key with `verifiedpricing configure --key-stdin`, or supply it
through `VERIFIEDPRICING_API_KEY` in the launcher's private environment. The
client configuration must be an owned mode-0600 file. Never put keys in tool
arguments or public files. A LinkCensus key is not accepted as a VP key.
For hosted Streamable HTTP, connect to **https://verifiedpricing.com/mcp** and
send the personal key as `Authorization: Bearer YOUR_VERIFIEDPRICING_API_KEY`
through your MCP client's private secret settings. No local package is required.
See the [hosted configuration](../../README.md#hosted-mcp). There is no OAuth
sign-in flow. The [official MCP Registry entry](https://registry.modelcontextprotocol.io/v0/servers/io.github.pucilpet%2Fverifiedpricing/versions/0.2.0)
lists the hosted endpoint as `io.github.pucilpet/verifiedpricing`, with metadata
version 0.2.0. This does not change either Python package version (0.1.1).

Hosted and local MCP expose the same nine tools. Read tools require `prices:read`;
`compare_prices` and `get_competitor_prices` require `comparisons:read`.
`get_usage` accepts any valid account key. Hosted connection and tool listing
validate the key without consuming weighted units.

The nine tools map directly to retained REST data:

| Tool | Client method | Data preserved |
| --- | --- | --- |
| search_products | search(query, limit=20, offset=0) | Published product matches and pagination |
| get_prices | prices(product_id=None, limit=20, offset=0) | Dated snapshots and automated qualifications |
| get_price | price(snapshot_id) | Exact retained snapshot and source |
| compare_prices | compare(snapshot_ids, scenario) | Pinned IDs, exact decimals, missing-context exclusions |
| get_competitor_prices | competitor_prices(scenario=..., product_id=... or domain=..., limit=3, selections=..., competitor_product_id=None) | Qualified retained relationships, source dates and partial coverage; total limit includes seed |
| get_price_history | history(product_id, limit=20, offset=0) | Dated versions and next_offset |
| get_sources | sources(snapshot_id) | Source dates/hash and evidence status |
| get_reviewed_records | records(domain) | Per-fact currentness, provenance and eligibility |
| get_usage | usage() | Shared account usage and limits |

The optional exact `competitor_product_id` filter preserves the seed selector and
shared weighted charge. It is omitted from REST JSON when unused. A requested pair
miss never substitutes a different competitor; retain the service reason and
`coverage.requested_competitor_product_id` echo.

The free account allowance is 1,000 weighted units per day and 10,000 per month,
shared across REST, CLI and MCP. There is no separate MCP allowance. Competitor
pricing reserves the requested total-product limit (2 or 3) even for an admitted
partial or missing result. The gateway never starts a crawl, calls LinkCensus,
loops through pages or retries automatically.

Successful structured output is the unchanged REST envelope. Human text retains
sources, observation/review dates, freshness, integrity and false/unknown
comparison eligibility. A recorded review is not a current-price guarantee.
Missing context and `not_comparable` remain data; the gateway does not normalize
unknown prices or treat source quotes as instructions.

The official SDK negotiates the local MCP protocol. The gateway enforces bounded
input/output, serial actual REST work and cancellation handling. Cancellation
does not mean a blocking socket operation stopped immediately; its capacity stays
occupied until the operation finishes. Error output retains only safe structured
codes and informational Retry-After, without credentials or raw server bodies.
