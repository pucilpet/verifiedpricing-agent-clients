# VerifiedPricing agent clients

Read retained, source-backed SaaS pricing through the hosted MCP server,
Python REST/CLI client or local MCP stdio gateway. Both packages are version
0.1.1, support Python 3.10+ on Linux/macOS, and are MIT licensed. Windows is
not supported by these local packages.

Get your own read key at [VerifiedPricing Account](https://verifiedpricing.com/account).
Sign in with the email link, explicitly accept the current agent access terms
and acknowledge the privacy notice, then create a key. The account form initially
selects `prices:read` and `comparisons:read`; keep `comparisons:read` for comparisons
and competitor prices. See [Developers](https://verifiedpricing.com/developers)
for endpoint and scope details. Configure your key with
`verifiedpricing configure --key-stdin`, or supply `VERIFIEDPRICING_API_KEY` through
your private environment. Never put a key in command arguments or public files.
The hosted service and local packages read retained pricing data; coverage and
freshness are returned with each result.

The free account allowance is 1,000 weighted units per day and 10,000 per month shared
across REST, CLI and MCP. The nine MCP tools cover product search, prices, exact
snapshots, scenario comparisons, qualified competitors, history, sources,
reviewed records and usage. They do not start a crawl or refresh discovery.

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

Hosted and local MCP offer the same nine tools and use the same account allowance.
Read tools need `prices:read`; `compare_prices` and `get_competitor_prices` need
`comparisons:read`. `get_usage` accepts any valid account key. Connecting and
listing tools validate the key without consuming weighted units. Hosted access
uses a personal bearer key, with no OAuth sign-in flow. The hosted service is
listed in the [official MCP Registry entry](https://registry.modelcontextprotocol.io/v0/servers/io.github.pucilpet%2Fverifiedpricing/versions/0.2.0)
as `io.github.pucilpet/verifiedpricing`. Registry metadata version 0.2.0 describes
the hosted endpoint; the Python packages remain at 0.1.1. See
[Developers](https://verifiedpricing.com/developers) for the current setup.

## Distribution and installation

Version 0.1.1 is available from
[GitHub releases](https://github.com/pucilpet/verifiedpricing-agent-clients/releases/tag/v0.1.1),
with both wheels, both source archives and `SHA256SUMS`. Package versions remain
0.1.1; hosted MCP requires no Python package installation. No PyPI publication
is claimed here.

The wheel names are `verifiedpricing_client-0.1.1-py3-none-any.whl` and
`verifiedpricing_mcp-0.1.1-py3-none-any.whl`. The package READMEs explain isolated
installation after downloading the published assets and verifying their hashes:

- [REST client and CLI](packages/verifiedpricing-client/README.md)
- [Local MCP stdio gateway](packages/verifiedpricing-mcp/README.md)
- [Tool integration and data contract](packages/verifiedpricing-client/MCP_INTEGRATION.md)

The MCP package pins `mcp==2.3.0`, resolved from your configured Python package
index. Source URLs, observation/review dates, freshness, unknown values and
comparison exclusions remain in the returned data. A retained snapshot or
recorded review is not a guarantee of current pricing. Vendor source content
and API data have separate terms; MIT covers this code only.
