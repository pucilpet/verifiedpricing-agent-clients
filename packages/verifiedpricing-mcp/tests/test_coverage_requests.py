"""Research requests remain explicit writes; existing lookups remain reads."""

import unittest

from verifiedpricing_mcp.runner import SerialRunner
from verifiedpricing_mcp.tools import IDEMPOTENT_TOOLS, TOOLS, WRITE_TOOLS, execute

REQUEST_ID = "cr_" + "a" * 32
ENVELOPE = {"schema_version": 1, "usage": {"day": {"used": 1}},
            "data": {"id": REQUEST_ID, "status": "queued", "domain": "product.example", "revision": 1}}


class CoverageClient:
    def __init__(self):
        self.calls = []

    def request_price_coverage(self, **arguments):
        self.calls.append(("request", arguments))
        return ENVELOPE

    def price_coverage_request(self, request_id):
        self.calls.append(("status", request_id))
        return ENVELOPE


class CoverageToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_request_preserves_payload_and_request_id(self):
        client = CoverageClient()
        arguments = {"domain": "product.example", "category": "seo", "consent": True}
        result, text, failed = await execute(client, SerialRunner(), "request_price_coverage", arguments)
        self.assertFalse(failed)
        self.assertIs(result, ENVELOPE)
        self.assertEqual(client.calls, [("request", arguments)])
        self.assertIn(REQUEST_ID, text)
        self.assertIn('status: "queued"', text)

    async def test_product_request_does_not_require_untrusted_domain_hint(self):
        client = CoverageClient()
        arguments = {"product_id": "product:existing.example", "consent": True}
        _, _, failed = await execute(client, SerialRunner(), "request_price_coverage", arguments)
        self.assertFalse(failed)
        self.assertEqual(client.calls, [("request", arguments)])

    async def test_known_domain_request_preserves_absent_category(self):
        client = CoverageClient()
        arguments = {"domain": "product.example", "consent": True}
        _, _, failed = await execute(client, SerialRunner(), "request_price_coverage", arguments)
        self.assertFalse(failed)
        self.assertEqual(client.calls, [("request", arguments)])
        self.assertNotIn("if", TOOLS["request_price_coverage"][1])

    async def test_bad_consent_targets_category_and_authority_fields_do_not_dispatch(self):
        client = CoverageClient()
        invalid = [{"product_id": "existing"}, {"product_id": "existing", "consent": False},
                   {"product_id": "existing", "consent": 1}, {"consent": True},
                   {"domain": "product.example", "category": "seo", "product_id": "existing", "consent": True},
                   {"domain": "https://product.example/pricing", "category": "seo", "consent": True},
                   {"domain": "product.example", "category": "arbitrary", "consent": True},
                   {"product_id": "existing", "consent": True, "source_url": "https://other.example"},
                   {"product_id": "existing", "consent": True, "api_key": "private"},
                   {"product_id": "existing", "consent": True, "force": True}]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                payload, _, failed = await execute(client, SerialRunner(), "request_price_coverage", arguments)
                self.assertTrue(failed)
                self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(client.calls, [])

    async def test_status_uses_only_account_status_method(self):
        client = CoverageClient()
        payload, _, failed = await execute(client, SerialRunner(), "get_price_coverage_request",
                                            {"request_id": REQUEST_ID})
        self.assertFalse(failed)
        self.assertIs(payload, ENVELOPE)
        self.assertEqual(client.calls, [("status", REQUEST_ID)])

    async def test_status_rejects_non_request_identity(self):
        client = CoverageClient()
        for value in ("other", "../prices", "cr_" + "A" * 32, True):
            _, _, failed = await execute(client, SerialRunner(), "get_price_coverage_request", {"request_id": value})
            self.assertTrue(failed)
        self.assertEqual(client.calls, [])

    def test_metadata_distinguishes_only_explicit_request_as_mutating(self):
        self.assertEqual(WRITE_TOOLS, {"request_price_coverage"})
        self.assertEqual(IDEMPOTENT_TOOLS, {"request_price_coverage", "get_price_coverage_request"})
        self.assertTrue(WRITE_TOOLS <= TOOLS.keys())
        self.assertTrue(IDEMPOTENT_TOOLS <= TOOLS.keys())
        self.assertEqual(TOOLS["request_price_coverage"][1]["properties"]["consent"]["const"], True)


if __name__ == "__main__":
    unittest.main()
