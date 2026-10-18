"""Private competitor-pricing contract fixtures; HTTP is fully mocked."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from verifiedpricing_client import Client, ClientError
from verifiedpricing_client.cli import main

SNAPSHOT = "po_" + "a" * 64
SECOND = "po_" + "b" * 64
THIRD = "po_" + "c" * 64
SCENARIO = {"as_of": "2026-10-17T12:00:00Z", "currency": "USD", "market": "US",
            "months": 12, "seats": 2, "usage_per_month": "0.12500001", "usage_unit": "requests"}
PAYLOAD = {"schema_version": 1, "usage": {"day": {"used": 3}}, "data": {
    "status": "partial", "reason": "synthetic_coverage_fixture",
    "seed": {"product_id": "product:example.com", "observed_at": "2026-10-01T10:00:00Z",
             "source_url": "https://example.com/pricing", "trust_label": "Automated pricing source; not human verified"},
    "competitors": [{"product_id": "product:other.example", "pricing_coverage": "unavailable"}],
    "discovery": {"edition": "synthetic-2026-01", "relationship": "candidate"},
    "comparison": {"status": "not_comparable", "reasons": ["missing_pricing"]},
    "selection_policy": {"fixture_note": "No nested production response schema is assumed"}}}


class Response(io.BytesIO):
    def __init__(self, payload=PAYLOAD, status=200, headers=None):
        super().__init__(json.dumps(payload).encode())
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}


class CompetitorClientTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(api_key="vp_competitor_fixture_not_real")
        patcher = patch.object(self.client._opener, "open", side_effect=lambda *args, **kwargs: Response())
        self.opened = patcher.start()
        self.addCleanup(patcher.stop)

    def sent_body(self):
        request = self.opened.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "https://verifiedpricing.com/api/v1/competitor-prices")
        return json.loads(request.data)

    def cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"VERIFIEDPRICING_API_KEY": "vp_competitor_fixture_not_real"}, clear=True):
                with patch("verifiedpricing_client.cli.Client", return_value=self.client):
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                        code = main(["--config", str(Path(temporary) / "unused.json"), *arguments])
        return code, output.getvalue(), error.getvalue()

    def arguments(self, *extra):
        return ["competitors", "--product-id", "product:example.com", "--currency", "USD", "--market", "US",
                "--as-of", "2026-10-17T12:00:00Z", "--months", "12", "--seats", "2", *extra]

    def test_product_seed_payload_preserves_scenario_selections_and_envelope(self):
        selections = {"product:example.com": SNAPSHOT, "product:other.example": SECOND}
        result = self.client.competitor_prices(product_id="product:example.com", scenario=SCENARIO, limit=2, selections=selections)
        self.assertEqual(result, PAYLOAD)
        self.assertEqual(self.sent_body(), {"product_id": "product:example.com", "scenario": SCENARIO,
                                           "limit": 2, "selections": selections})
        self.assertEqual(self.opened.call_count, 1)

    def test_domain_seed_default_limit_is_total_including_seed(self):
        self.client.competitor_prices(domain="example.com", scenario=SCENARIO)
        self.assertEqual(self.sent_body(), {"domain": "example.com", "scenario": SCENARIO, "limit": 3})

    def test_invalid_seed_limit_or_selection_never_issues_http(self):
        invalid = [dict(), {"product_id": "seed", "domain": "example.com"}, {"product_id": "bad/id"},
                   {"product_id": "x" * 129}, {"domain": "Example.com"}, {"domain": "example.com."},
                   {"domain": "https://example.com"}, {"domain": "127.0.0.1"}]
        invalid.extend({"product_id": "seed", "limit": value} for value in (1, 4, True, "3", 3.0))
        invalid.extend({"product_id": "seed", "selections": value} for value in (
            [], {"seed": "invalid"}, {"bad/id": SNAPSHOT}, {"": SNAPSHOT},
            {"a": SNAPSHOT, "b": SECOND, "c": THIRD, "d": SNAPSHOT}))
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ClientError):
                self.client.competitor_prices(scenario=SCENARIO, **arguments)
        self.opened.assert_not_called()

    def test_scenario_authority_unknown_fields_and_decimal_bounds_rejected_before_http(self):
        invalid = [{**SCENARIO, "api_key": "private"}, {**SCENARIO, "prices": []},
                   {**SCENARIO, "provenance": "human_reviewed"}, {**SCENARIO, "months": True},
                   {**SCENARIO, "seats": 0}, {**SCENARIO, "as_of": "2026-10-17"},
                   {**SCENARIO, "currency": "usd"}, {**SCENARIO, "allow_stale": "true"},
                   {**SCENARIO, "usage_per_month": True}, {**SCENARIO, "usage_per_month": 0.1},
                   {**SCENARIO, "usage_per_month": "NaN"}, {**SCENARIO, "usage_per_month": "1e999999"},
                   {**SCENARIO, "usage_per_month": "0.000000001"}, {**SCENARIO, "usage_per_month": "1000000000000000000"}]
        for scenario in invalid:
            with self.subTest(scenario=scenario), self.assertRaises(ClientError):
                self.client.competitor_prices(product_id="seed", scenario=scenario)
        self.opened.assert_not_called()

    def test_exact_integer_and_scientific_decimal_scenarios_remain_exact(self):
        for quantity in (1, "1e-8", "999999999999999999", "0.00000001"):
            self.client.competitor_prices(product_id="seed", scenario={**SCENARIO, "usage_per_month": quantity})
            self.assertEqual(self.sent_body()["scenario"]["usage_per_month"], quantity)

    def test_cli_selection_and_json_payload_are_exact(self):
        code, output, error = self.cli(self.arguments("--limit", "2", "--usage-per-month", "0.12500001",
            "--usage-unit", "requests", "--select", "product:example.com=" + SNAPSHOT, "--json"))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output), PAYLOAD)
        body = self.sent_body()
        self.assertEqual(body["limit"], 2)
        self.assertEqual(body["selections"], {"product:example.com": SNAPSHOT})
        self.assertEqual(body["scenario"]["usage_per_month"], "0.12500001")

    def test_cli_domain_seed_and_human_output_preserve_service_fields(self):
        arguments = self.arguments()
        arguments[1:3] = ["--domain", "example.com"]
        code, output, error = self.cli(arguments)
        self.assertEqual((code, error), (0, ""))
        for text in ("status: \"partial\"", "seed:", "competitors:", "pricing_coverage", "unavailable",
                     "2026-10-01T10:00:00Z", "https://example.com/pricing", "not human verified", "missing_pricing"):
            self.assertIn(text, output)
        self.assertEqual(self.sent_body()["domain"], "example.com")

    def test_cli_rejects_both_seeds_duplicate_or_excess_selections_without_echo(self):
        invalid = [self.arguments("--domain", "example.com"), self.arguments("--limit", "4"),
                   self.arguments("--select", "seed=" + SNAPSHOT, "--select", "seed=" + SECOND),
                   self.arguments("--select", "vp_competitor_fixture_not_real"),
                   self.arguments(*sum((["--select", "product" + str(index) + "=" + SNAPSHOT] for index in range(4)), []))]
        for arguments in invalid:
            code, output, error = self.cli(arguments)
            self.assertEqual(code, 2)
            self.assertNotIn("vp_competitor_fixture_not_real", output + error)
        self.opened.assert_not_called()

    def test_rate_error_preserves_retry_after_without_retries(self):
        self.opened.side_effect = lambda *args, **kwargs: Response({"detail": {"code": "quota_exceeded"}}, 429, {"Retry-After": "60"})
        with self.assertRaises(ClientError) as caught:
            self.client.competitor_prices(product_id="seed", scenario=SCENARIO)
        self.assertEqual((caught.exception.status, caught.exception.retry_after), (429, "60"))
        self.assertEqual(self.opened.call_count, 1)


if __name__ == "__main__":
    unittest.main()
