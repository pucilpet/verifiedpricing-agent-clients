# VerifiedPricing client 0.1.2

Python 3.10+ REST client and `verifiedpricing` command. Runtime uses only the Python
standard library. Supported platforms: Linux and macOS with POSIX ownership/mode
checks. Windows credential-file support is not implemented.

Get your own API key at [VerifiedPricing Account](https://verifiedpricing.com/account).
Sign in with the email link, explicitly accept the current agent access terms
and acknowledge the privacy notice, then create a key. The account form initially
selects `prices:read` and `comparisons:read`; keep `comparisons:read` selected for
scenario comparisons and competitor prices. See [Developers](https://verifiedpricing.com/developers)
for endpoint and scope details. A LinkCensus key is not a VerifiedPricing key.
Add `coverage:request` when you want a key to queue pricing research. The two read
scopes remain the default. Website sign-in provides your personal key.

The free account allowance is **1,000 weighted units per day and 10,000 per month per
account**, shared by REST, this CLI and MCP. It is not a separate allowance per
key or transport. Consult `usage` for the account's returned limits and remaining
budget. Admitted operations can consume units even when data is missing or partial.

Client 0.1.2 adds explicit coverage requests. These commands require an API with
coverage requests enabled and a key with the optional `coverage:request` scope.

## Install and run

The intended distribution channel is the
[GitHub prerelease](https://github.com/pucilpet/verifiedpricing-agent-clients/releases/tag/v0.3.0),
not PyPI. Installation is available only when that release lists its reviewed
assets and checksums. The expected client asset is
`verifiedpricing_client-0.1.2-py3-none-any.whl`. Do not substitute an unreviewed
source checkout or guess a missing download/hash.

After downloading that wheel and `SHA256SUMS` from the published release, verify
the checksum with `sha256sum -c SHA256SUMS` (Linux) or
`shasum -a 256 -c SHA256SUMS` (macOS), then install into an isolated environment:

```sh
python3 -m venv ~/.venvs/verifiedpricing
~/.venvs/verifiedpricing/bin/python -m pip install --no-index --no-deps \
  ./verifiedpricing_client-0.1.2-py3-none-any.whl
~/.venvs/verifiedpricing/bin/verifiedpricing --version
~/.venvs/verifiedpricing/bin/verifiedpricing --help
```

Run the commands below using that environment's executable or activate its
virtual environment. The client has no third-party runtime dependencies.
Building from source uses setuptools >=68.

Use an environment key provided through your shell's secret-input mechanism, or
pipe an existing key to private configuration. Never put a key in command arguments:

```sh
secret-tool lookup service verifiedpricing | verifiedpricing configure --key-stdin
verifiedpricing prices --product-id product_id --limit 10 --json
verifiedpricing search notion --json
verifiedpricing history product_id --offset 0
verifiedpricing price po_<64-lowercase-hex-characters> --json
verifiedpricing sources po_<64-lowercase-hex-characters>
verifiedpricing records example.com --json
verifiedpricing usage --json
```

`secret-tool` is an optional example OS credential store, not a dependency. If
`VERIFIEDPRICING_API_KEY` is set, `configure` can save it without `--key-stdin`.
Configuration defaults to `$XDG_CONFIG_HOME/verifiedpricing/config.json` or
`~/.config/verifiedpricing/config.json`; `--config PATH` overrides it. Files must
be owned regular files with exactly mode 0600. Writes use a private directory,
0600 temporary file, fsync and atomic replacement. Symlink files are rejected.
Environment credentials take precedence and skip reading the configuration file;
in that case supply `--base-url` for a custom endpoint. No project `.env` is read.
Unset credentials make an anonymous request; supplied invalid credentials are
never silently removed or retried as anonymous.

Compare two or three distinct, pinned snapshot IDs (replace placeholders):

```sh
verifiedpricing compare po_<snapshot-a> po_<snapshot-b> \
  --currency USD --market US --months 12 --seats 5 \
  --usage-per-month 100.125 --usage-unit requests \
  --as-of 2026-10-17T12:00:00Z --json
```

Currency, market and timezone-aware `--as-of` are required. Months default to 12,
seats to 1. Usage is transmitted as an exact decimal string; the client does not
calculate, FX-convert, guess missing prices or upgrade automated provenance.
`not_comparable` remains an ordinary successful data response with explicit reasons.

## Queue pricing research

With client 0.1.2, request coverage for an existing product ID or a
canonical lowercase domain. A new domain needs a category hint: `seo`,
`email marketing`, `crm`, `analytics`, `project management`, `customer support`,
`social media` or `hosting`. An optional `--product-name` accepts 1 to 120
characters. The crawler qualifies the product using its official pages.
For a known domain, the API can use its existing category; omit hints when
replaying a request originally created without them.

```sh
verifiedpricing coverage-request --domain example.com --category crm --consent --json
verifiedpricing coverage-request --product-id product:existing.example --consent --json
verifiedpricing coverage-status cr_<32-lowercase-hex-characters> --json
```

The request needs the explicit `coverage:request` key scope and `--consent`.
Creating the first request for an account and target uses one shared API unit.
Repeating the same request returns its original ID without another debit;
conflicting category or name hints are rejected. `coverage-status` needs
`prices:read` and uses no allowance units, with execution limits still applying.

Research runs through the regular paced crawl. Status can be `queued`, `deferred`,
`researching`, `processing`, `publication_pending`, `held` or `available`.
For `held`, read the returned reason. An `available` result supplies the published
`snapshot_id`. The response preserves the requested domain and, when established,
the separately validated `canonical_domain`. A missing price lookup stays a
read; use the separate request command to queue work.

Competitor pricing uses `POST /api/v1/competitor-prices` when enabled for the
account API. An older backend does not gain this route by installing a client.
The read uses retained, qualified relationships and available pricing data; it
makes no live LinkCensus query or automatic crawl. Missing or partial coverage
remains explicit and does not establish complete market coverage.

```sh
verifiedpricing competitors --product-id product:example.com \
  --currency USD --market US --months 12 --seats 2 \
  --as-of 2026-10-17T12:00:00Z --limit 2 \
  --competitor-product-id product:other.example \
  --select 'product:example.com=po_<64-lowercase-hex-characters>' --json
```

Add `--competitor-product-id product:other.example` to select an exact
competitor product ID (Python: `competitor_product_id="product:other.example"`).
The service restricts the read to that published qualified directed relationship.
Omitting the filter preserves the existing bounded selection. No other competitor
substitutes for an unavailable requested pair: the response is partial with
`requested_competitor_not_current`. Every filtered data response echoes the exact
ID in `coverage.requested_competitor_product_id`, including unavailable or
ambiguous seed responses. Seed ambiguity and integrity failures retain their
existing behavior. The total `limit` still determines the charge (2 or 3).

Choose exactly one `--product-id` or canonical lowercase `--domain`. `--limit`
is **total products including the seed**, either 2 or 3 (default 3). Up to three
distinct `--select PRODUCT_ID=SNAPSHOT_ID` options pin explicit selections;
duplicate product selections fail. Product IDs support letters, digits, colon,
underscore, dot and hyphen, including `product:example.com`. Currency, market,
timezone-aware time and scenario options match `compare`. Partial/unavailable
coverage, source dates and exclusions remain service data; human output renders
the returned fields without guessing the nested discovery/comparison schema.
The API requires `comparisons:read` and reserves `limit` weighted units once even
when the retained result is partial or missing. Client code does not grant that
scope or simulate a quota receipt.

`records DOMAIN` reads published reviewed facts and history. Each fact retains its
own currentness, provenance, review/capture dates, source, freshness, integrity and
badge/comparison eligibility. Missing sources and dates display as `unknown`;
stale historical review remains stale. Reviewed facts requiring normalization
keep `comparison_eligible: false`; this command grants no comparison readiness
or current-price guarantee.

`--json` before or after a command prints the server's schema-version-1 envelope
on stdout. Decimal strings, snapshots, citations and trust fields are preserved.
Errors print `{"schema_version":1,"error":{"code":...,"message":...,"status":...,"retry_after":...}}`
on stderr with no stdout response. Server error text is intentionally not echoed.
Human output retains sources, observation dates, trust labels and comparison
exclusions; use JSON for the complete data contract. Help/version use normal
terminal text. Parser errors redact argument values.

Exit statuses: 0 success; 2 arguments/configuration/local I/O; 3 authentication or
scope; 4 rate/quota limit; 5 unavailable snapshot (404); 6 API/transport/protocol
failure. Retry-After is returned as seconds or HTTP-date text; no retry occurs.

HTTPS origins are required. Local fixture development must explicitly pass both
`--base-url http://127.0.0.1:PORT --allow-localhost`. HTTP is otherwise refused,
including nonlocal origins. TLS validation uses Python defaults; no insecure
override exists. Redirects are refused, environment proxies are disabled, and no
cookies are used. Network operations default to a 15-second socket timeout
(maximum 60); each response is capped at 512 KiB. This socket timeout is not a
whole-command wall-clock deadline. Pages are bounded to 1..50 rows with offset
0..10000; the client exposes next_offset without automatically consuming pages.

## Reusable client

```python
import os
from verifiedpricing_client import Client, ClientError

client = Client(api_key=os.environ["VERIFIEDPRICING_API_KEY"])
result = client.prices(product_id="product_id", limit=10)
```

Methods: `prices`, `price`, `compare`, `competitor_prices`, `search`, `history`, `sources`, `records`, `usage`.
`ClientError` exposes a safe code, message, HTTP status and Retry-After value for
adapters. The separate `verifiedpricing-mcp` package provides local stdio; this
library does not implement OAuth.

The new method uses keyword arguments:
`client.competitor_prices(product_id="product:example.com", scenario={"as_of":
"2026-10-17T12:00:00Z", "currency":"USD", "market":"US"}, limit=3,
selections={...}, competitor_product_id="product:other.example")`. Use `domain="example.com"` instead of `product_id` for a domain
seed. Its success result is the unchanged standard REST envelope.

## Development checks

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Tests use disposable private configuration and a loopback-only fixture server.
They do not require an account key. The optional offline wheel check is
`scripts/clean_install_smoke.py`: without `--execute` it prints a plan; with
`--execute` it installs only a supplied wheel in a disposable environment and
runs local console/fixture checks. It does not publish or test a live account.

See [MCP_INTEGRATION.md](MCP_INTEGRATION.md) for the separate stdio gateway.

## Data attribution and reuse

The MIT license covers this client code only. API data and cited vendor source
content do not acquire an MIT license from this package. Retain source URLs,
snapshot IDs, original observation/review dates and explicit trust/freshness
states when quoting results. No independent data redistribution or caching terms
are asserted here; review the service's published terms before redistribution.
Do not treat a cached snapshot as a guarantee of current pricing. Refetch when
current publication, dispute, withdrawal or integrity status matters.
