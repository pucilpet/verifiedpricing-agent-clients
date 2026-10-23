# VerifiedPricing agent clients

Python REST client, CLI and MCP tools for pricing snapshots, source citations,
comparisons and explicit research requests.

Bundle **v0.3.1** pairs **verifiedpricing-client 0.1.3** with
**verifiedpricing-mcp 0.3.1**. The CLI and local stdio support Python 3.10+
on Linux and macOS. Self-hosted HTTP extras require Python 3.11+.
Connecting to the hosted endpoint requires no Python installation.

MCP 0.3.2 is in release validation for Python 3.10 stdio deadlines.
The download links below refer to published bundle v0.3.1.

## Get started

Create your own key at [VerifiedPricing Account](https://verifiedpricing.com/account).
The account form initially selects `prices:read` and `comparisons:read`;
API key creation with scopes omitted defaults to `prices:read` only. Add the optional
`coverage:request` scope if you want to submit pricing research requests.
Keep your key in private environment or credential storage; do not put it in
command arguments, URLs, tool arguments or public configuration.

[Bundle v0.3.1](https://github.com/pucilpet/verifiedpricing-agent-clients/releases/tag/v0.3.1)
uses these wheel filenames:

- `verifiedpricing_client-0.1.3-py3-none-any.whl`
- `verifiedpricing_mcp-0.3.1-py3-none-any.whl`

Download both wheels and `SHA256SUMS` from the release assets, verify their
checksums, then install in an isolated environment:

```sh
sha256sum -c SHA256SUMS
python3 -m venv ~/.venvs/verifiedpricing-agent
~/.venvs/verifiedpricing-agent/bin/python -m pip install \
  ./verifiedpricing_client-0.1.3-py3-none-any.whl \
  ./verifiedpricing_mcp-0.3.1-py3-none-any.whl
```

On macOS, use `shasum -a 256 -c SHA256SUMS`. The REST client uses the Python
standard library; the MCP package installs the pinned official SDK `mcp==2.3.0`
and its dependencies. Activate the environment before using `verifiedpricing`
or configuring `verifiedpricing-mcp` as a local stdio server.

## Hosted MCP


Connect a client that supports Streamable HTTP to **https://verifiedpricing.com/mcp**.
Send your personal read key in `Authorization: Bearer YOUR_VERIFIEDPRICING_API_KEY`.
Store the real key in your client's private secret or environment settings; never
put it in the URL or a public configuration file. The JSON below shows the shape
used by clients that accept `mcpServers` HTTP configuration; client support and
secret substitution vary.

```json
{
  "mcpServers": {
    "verifiedpricing": {
      "type": "http",
      "url": "https://verifiedpricing.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_VERIFIEDPRICING_API_KEY"
      }
    }
  }
}
```

The hosted endpoint uses the same personal account allowance. Its MCP Registry
[entry, metadata version 0.3.0](https://registry.modelcontextprotocol.io/v0/servers/io.github.pucilpet%2Fverifiedpricing/versions/0.3.0),
records the service endpoint. Use the tool list returned by the running service
when connecting. The local 0.3.1 package provides the eleven tools below.

## Eleven MCP tools

`search_products`, `get_prices`, `get_price`, `compare_prices`,
`get_competitor_prices`, `get_price_history`, `get_sources`,
`get_reviewed_records`, `get_usage`, `request_price_coverage`,
`get_price_coverage_request`.

Coverage tools require an API with coverage requests enabled.
`request_price_coverage` is the optional write tool. It requires
`coverage:request`, explicit `consent: true`, and a product ID or canonical
domain. A new domain also needs a supported category. Repeating the same request
returns its original ID; use `get_price_coverage_request` to follow its status.
Price lookups remain reads when coverage is missing.

REST, CLI and MCP share the same account budget: the free allowance is
1,000 weighted units per day and 10,000 per month. `get_usage` returns the account's
limits and remaining allowance. A new key or MCP session does not reset them.

## Source-backed results

Client 0.1.3 and MCP 0.3.1 retain catalog provenance, amount support, comparison
eligibility, conditions, billing and provider retrieval dates in human output.
Catalog entries carry the Automated pricing source label.

Responses retain snapshot IDs, source URLs, observation and review dates,
freshness, integrity and comparison eligibility. Automated observations and
recorded human review have distinct labels. Comparisons preserve
`not_comparable` and its reasons when inputs need more context.

## License and data terms

Client and gateway code are MIT licensed. Copyright (c) 2026 VerifiedPricing
contributors. Include the copyright and permission notice from `LICENSE` with
copies or substantial portions of the software.

The code license does not license service data or cited vendor content.
[Service terms](https://verifiedpricing.com/terms) govern API use and data reuse;
retain citations, snapshot IDs, original dates and returned trust fields.
