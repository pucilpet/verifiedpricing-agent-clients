# 0.3.0 - Unreleased

- Add opt-in `request_price_coverage` and read-only `get_price_coverage_request` tools.
- Advertise the request tool as an idempotent write; existing read tool annotations stay read-only.
- Require client 0.1.2 and retain the official mcp 2.3.0 SDK.

# 0.2.0 source candidate

- Add an optional, separately operated hosted Streamable HTTP entrypoint using
  the official SDK, the same nine tool schemas and client 0.1.1 compatibility.
- Authenticate personal header keys through existing zero-debit usage reads;
  preserve shared API scopes, revocation, quotas and source qualifications.
- Bound concurrency, bodies, outputs and deadlines; cancel owned async I/O on
  disconnect. Use a product-namespaced reusable HTTP boundary.
- No 0.2.0 distribution or production deployment is claimed by this source entry.
  Existing 0.1.1 published artifacts remain unchanged.

# Changelog

## 0.1.1 - Candidate

- Optional exact competitor product filter in the existing competitor-pricing tool.
- Pins verifiedpricing-client 0.1.1; retains the official mcp 2.3.0 SDK and nine tools.
- Keeps REST identities, response coverage and shared weighted quota unchanged.

## 0.1.0 - Early access

- Official-SDK local stdio gateway with nine fixed VerifiedPricing tools,
  including qualified retained competitor-pricing reads.
- Unchanged source-backed REST envelopes with observation/review dates,
  freshness, missing context and comparison exclusions preserved.
- Bounded byte framing, serial admission, cancellation capacity and output.
- Uses the same account allowance as REST and CLI; no automatic crawl,
  pagination loop or retry. API pilot credentials are issued separately.
- Hosted OAuth, PyPI and MCP Registry distribution are not provided here.
