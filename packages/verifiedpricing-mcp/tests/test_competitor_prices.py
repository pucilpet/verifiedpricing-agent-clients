"""Fixed competitor-pricing tool contract; no HTTP or SDK protocol mocks."""

import unittest

from verifiedpricing_mcp.runner import SerialRunner
from verifiedpricing_mcp.tools import TOOLS, execute

SNAPSHOT = "po_" + "a" * 64
SCENARIO = {"as_of": "2026-10-17T12:00:00Z", "currency": "USD", "market": "US", "usage_per_month": "0.125"}
PAYLOAD = {"schema_version": 1, "data": {"status": "partial", "reason": "synthetic_fixture",
    "seed": {"product_id": "product:example.com", "source_url": "https://example.com/pricing", "observed_at": "2026-10-01T00:00:00Z"},
    "competitors": [{"pricing_coverage": "unavailable"}], "discovery": {"edition": "fixture-2026-01"},
    "comparison": {"status": "not_comparable"}, "selection_policy": "synthetic test only"}, "usage": {"day": {"used": 3}}}


class Client:
    def __init__(self):
        self.calls = []

    def competitor_prices(self, **arguments):
        self.calls.append(arguments)
        return PAYLOAD


class CompetitorToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_tool_forwards_exact_payload_and_preserves_qualifications(self):
        client = Client()
        arguments = {"product_id": "product:example.com", "scenario": SCENARIO, "limit": 3,
                     "selections": {"product:example.com": SNAPSHOT}}
        payload, text, failed = await execute(client, SerialRunner(), "get_competitor_prices", arguments)
        self.assertFalse(failed)
        self.assertIs(payload, PAYLOAD)
        self.assertEqual(client.calls, [arguments])
        for value in ("partial", "pricing_coverage", "unavailable", "not_comparable", "2026-10-01", "https://example.com/pricing"):
            self.assertIn(value, text)
        self.assertIn("not human verification", text)

    async def test_domain_seed_and_optional_defaults_are_forwarded_without_fabricated_selections(self):
        client = Client()
        arguments = {"domain": "example.com", "scenario": SCENARIO}
        _, _, failed = await execute(client, SerialRunner(), "get_competitor_prices", arguments)
        self.assertFalse(failed)
        self.assertEqual(client.calls, [arguments])

    async def test_schema_and_runtime_reject_seed_limit_selection_and_authority_ambiguity(self):
        client = Client()
        baseline = {"product_id": "product:example.com", "scenario": SCENARIO}
        invalid = [{"scenario": SCENARIO}, {**baseline, "domain": "example.com"}, {**baseline, "product_id": "bad/id"},
                   {"domain": "https://example.com", "scenario": SCENARIO}, {**baseline, "limit": 1},
                   {**baseline, "limit": 4}, {**baseline, "limit": True}, {**baseline, "selections": {"seed": "invalid"}},
                   {**baseline, "selections": {"bad/id": SNAPSHOT}}, {**baseline, "selections": {str(i): SNAPSHOT for i in range(4)}},
                   {**baseline, "api_key": "secret"}, {**baseline, "base_url": "https://other.example"},
                   {**baseline, "scenario": {**SCENARIO, "verified": True}}, {**baseline, "scenario": {**SCENARIO, "as_of": "2026-10-17"}}]
        for arguments in invalid:
            payload, _, failed = await execute(client, SerialRunner(), "get_competitor_prices", arguments)
            self.assertTrue(failed)
            self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(client.calls, [])
        schema = TOOLS["get_competitor_prices"][1]
        self.assertEqual(schema["oneOf"], [{"required": ["product_id"]}, {"required": ["domain"]}])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["selections"]["maxProperties"], 3)
        self.assertIn("Total product count including the seed", schema["properties"]["limit"]["description"])


if __name__ == "__main__":
    unittest.main()
