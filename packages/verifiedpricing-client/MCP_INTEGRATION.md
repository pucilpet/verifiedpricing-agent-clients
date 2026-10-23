# Local MCP integration

The upcoming `verifiedpricing-mcp==0.3.1` gateway uses
`verifiedpricing-client==0.1.3` and the official `mcp==2.3.0` SDK. The client stays
stdlib-only. See the [gateway README](../verifiedpricing-mcp/README.md) for
release assets, installation, launch configuration and process limits.

Get your own API key at [VerifiedPricing Account](https://verifiedpricing.com/account).
Sign in with the email link, explicitly accept the current agent access terms
and acknowledge the privacy notice, then create a key. The account form initially
selects `prices:read` and `comparisons:read`; keep `comparisons:read` for comparisons
and competitor prices. See [Developers](https://verifiedpricing.com/developers)
for endpoint and scope details.

Configure the key with `verifiedpricing configure --key-stdin`, or supply it
through `VERIFIEDPRICING_API_KEY` in the launcher's private environment. The
client configuration must be an owned mode-0600 file. Never put keys in tool
arguments or public files. A LinkCensus key is not accepted as a VP key.
The current hosted service is at `https://verifiedpricing.com/mcp`, using a
personal Authorization header key. The new coverage tools described here await
their gateway/client release and API activation.

The eleven tools map to bounded REST operations:

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
| request_price_coverage | request_price_coverage(consent=True, product_id=... or domain=..., category=..., product_name=...) | Your deduplicated research request ID and status; explicit `coverage:request` grant |
| get_price_coverage_request | price_coverage_request(request_id) | Account-owned request status and published snapshot ID |

The optional exact `competitor_product_id` filter preserves the seed selector and
shared weighted charge. It is omitted from REST JSON when unused. A requested pair
miss never substitutes a different competitor; retain the service reason and
`coverage.requested_competitor_product_id` echo.

The free account allowance is 1,000 weighted units per day and 10,000 per month,
shared across REST, CLI and MCP. There is no separate MCP allowance. Competitor
pricing reserves the requested total-product limit (2 or 3) even for an admitted
partial or missing result. Existing read tools use retained data. To queue pricing
research, use `request_price_coverage` with explicit consent and the optional write
grant. The request costs one unit when first created; an identical repeat returns
the same ID without another debit. Request status polling uses no units and remains
subject to execution limits. The crawler handles accepted demand on its regular
schedule. The gateway performs no pagination loop or automatic retry.

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
