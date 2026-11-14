# Your first source-backed pricing check

Turn a product question into a dated, cited answer with VerifiedPricing. This walkthrough uses the hosted MCP endpoint, so there is no Python installation step.

## 1. Connect once

Create your personal key at [VerifiedPricing Account](https://verifiedpricing.com/account). For this read-only walkthrough, use `prices:read`; add `comparisons:read` only for the optional comparison below. Follow the account's terms and privacy steps.

In a client supporting Streamable HTTP and a private Authorization header, connect to:

```text
https://verifiedpricing.com/mcp
```

Set the header to `Authorization: Bearer YOUR_VERIFIEDPRICING_API_KEY` using your client's private credential settings. Never paste a real key into the conversation, URL or repository. See the [hosted setup](../README.md#hosted-mcp) for a configuration example.

## 2. Ask a useful first question

Replace the bracketed product name, then paste this prompt into your connected assistant:

> Find published pricing information for [product name] using VerifiedPricing. Search for the product first and ask me to choose if the identity is ambiguous. Read one relevant pricing snapshot and its sources. Return the plan name, supported amount and currency, billing conditions, snapshot ID, source URL, observation date and trust/freshness qualifications. Clearly separate automated observations from recorded human review. Do not guess missing prices, call an old snapshot today's price, or queue new research. If coverage is missing, say so.

The expected tool sequence is:

1. `search_products` to find the exact product.
2. `get_prices` with the returned product ID and a small explicit limit.
3. `get_price` with a returned snapshot ID.
4. `get_sources` for that same snapshot.

These are real tool names from the local package. Check the connected service's returned tool list before use. Do not invent product or snapshot IDs. The service may return no usable record.

## 3. Make the answer reusable

Ask for this structure, populated only from the returned evidence:

| Field | What to preserve |
| --- | --- |
| Product and plan | Exact identity, not a similarly named product |
| Amount | Currency, unit, period and any support/eligibility conditions |
| Timing | Original observation date and returned freshness state |
| Evidence | Source URL and snapshot ID |
| Trust | Automated source versus recorded human review, including exclusions |
| Unknowns | Missing context, integrity warnings or unavailable coverage |

This is an answer format, not a sample result. No current vendor prices or customer outcomes are asserted here. Check the vendor's current checkout terms before a purchase decision.

## Optional: compare two plans on the same basis

Use two distinct snapshot IDs already returned by the service. With `comparisons:read`, ask:

> Compare these two pinned snapshots for my scenario: [market], [currency], [number of seats], [number of months] and [timezone-aware as-of time]. If usage-based, use [exact usage per month] and [usage unit]. Use compare_prices. Preserve not_comparable and every reason or qualification. Do not convert currencies, fill missing terms or rank an unsupported result as cheaper.

The `compare_prices` tool accepts two or three distinct snapshot IDs and a scenario. Currency, market and a timezone-aware `as_of` are required. A `not_comparable` result is useful information, not permission to guess. The [tool reference](../packages/verifiedpricing-mcp/README.md#tools-and-truth) describes the full inputs.

## If something stops the walkthrough

- **Wrong or ambiguous product:** choose the exact identity before reading prices.
- **No published coverage:** report the gap. Requesting research is a separate optional write action requiring `coverage:request` and explicit consent; this walkthrough never submits it.
- **Authentication/scope error:** check the personal key and required read scopes in private settings. Do not share the key to debug it.
- **Quota/rate limit:** check `get_usage` and the returned limits. Do not create another key to bypass them or retry automatically.
- **Stale or unsupported evidence:** retain its original date and exclusions. Do not promote automated data to human-reviewed status.

REST, CLI and MCP use the same account allowance. Calls can consume weighted units even when results are partial. The [client documentation](../packages/verifiedpricing-client/README.md) explains budgets, data reuse and local alternatives.
