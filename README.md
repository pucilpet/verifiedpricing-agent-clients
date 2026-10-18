# VerifiedPricing agent clients

Early-access Python REST/CLI client and local MCP stdio gateway for retained,
source-backed SaaS pricing data. Both packages are version 0.1.0, support
Python 3.10+ on Linux/macOS, and are MIT licensed. Windows is not supported.

API pilot credentials are issued separately. There is no open API sign-up,
hosted MCP endpoint or hosted OAuth flow. Ask the maintainer for pilot access
and current endpoint availability. A package download does not activate an
account or establish live pricing coverage.

The account allowance is 1,000 weighted units per day and 10,000 per month shared
across REST, CLI and MCP. The nine MCP tools cover product search, prices, exact
snapshots, scenario comparisons, qualified competitors, history, sources,
reviewed records and usage. They do not start a crawl or refresh discovery.

## Distribution and installation

The intended early-access distribution is
[GitHub prerelease v0.1.0](https://github.com/pucilpet/verifiedpricing-agent-clients/releases/tag/v0.1.0).
Use only assets and SHA-256 checksums actually listed on that release; it may
remain unavailable until package gates and publication complete. No PyPI package
publication or MCP Registry listing is claimed here.

Expected wheel names are `verifiedpricing_client-0.1.0-py3-none-any.whl` and
`verifiedpricing_mcp-0.1.0-py3-none-any.whl`. The package READMEs explain isolated
installation after downloading the published assets and verifying their hashes:

- [REST client and CLI](packages/verifiedpricing-client/README.md)
- [Local MCP stdio gateway](packages/verifiedpricing-mcp/README.md)
- [Tool integration and data contract](packages/verifiedpricing-client/MCP_INTEGRATION.md)

The MCP package pins `mcp==2.3.0`, resolved from your configured Python package
index. Source URLs, observation/review dates, freshness, unknown values and
comparison exclusions remain in the returned data. A retained snapshot or
recorded review is not a guarantee of current pricing. Vendor source content
and API data have separate terms; MIT covers this code only.
