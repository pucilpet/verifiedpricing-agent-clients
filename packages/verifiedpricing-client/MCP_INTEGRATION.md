# Local MCP integration

`verifiedpricing-mcp==0.1.0` is a separate local stdio gateway over
`verifiedpricing-client==0.1.0` and the official `mcp==2.3.0` SDK. The client stays
stdlib-only. See the [gateway README](../verifiedpricing-mcp/README.md) for
release assets, installation, launch configuration and process limits.

API pilot credentials are issued separately. There is no open API sign-up,
hosted MCP endpoint, hosted OAuth flow or MCP Registry listing. Supply your own
VerifiedPricing key through the launcher's private environment or the client's
owned mode-0600 configuration, never tool arguments or public files. A
LinkCensus key is not accepted as a VP key.

The nine tools map directly to retained REST data:

| Tool | Client method | Data preserved |
| --- | --- | --- |
| search_products | search(query, limit=20, offset=0) | Published product matches and pagination |
| get_prices | prices(product_id=None, limit=20, offset=0) | Dated snapshots and automated qualifications |
| get_price | price(snapshot_id) | Exact retained snapshot and source |
| compare_prices | compare(snapshot_ids, scenario) | Pinned IDs, exact decimals, missing-context exclusions |
| get_competitor_prices | competitor_prices(scenario=..., product_id=... or domain=..., limit=3, selections=...) | Qualified retained relationships, source dates and partial coverage; total limit includes seed |
| get_price_history | history(product_id, limit=20, offset=0) | Dated versions and next_offset |
| get_sources | sources(snapshot_id) | Source dates/hash and evidence status |
| get_reviewed_records | records(domain) | Per-fact currentness, provenance and eligibility |
| get_usage | usage() | Shared account usage and limits |

The pilot account allowance is 1,000 weighted units per day and 10,000 per month,
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
