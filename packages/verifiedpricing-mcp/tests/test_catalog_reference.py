"""Catalog prices retain their limitations in text and their exact structured data."""

import json
import unittest
from unittest.mock import Mock

from verifiedpricing_mcp.runner import SerialRunner
from verifiedpricing_mcp.tools import MAX_TEXT_BYTES, execute


class CatalogReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_qualification_survives_mcp_text_and_structured_payload(self):
        row = {"id": "po_" + "a" * 64, "product": "Catalog fixture", "amount": "9.10",
               "currency": None, "billing_interval": "Billed annually", "conditions": "Prepay 12 months",
               "source_kind": "provider_retrieved_text", "observed_at": None,
               "retrieved_at": "2026-10-08T12:34:56Z", "verified_at": None, "source_hash": None,
               "amount_supported": False, "comparison_eligible": False,
               "catalog_reference": {"catalog_id": "original100-reference-v1", "catalog_sha256": "b" * 64,
                   "row_sha256": "c" * 64, "currency_display": "$",
                   "capture_qualification": "provider retrieval; upstream capture time unknown"}}
        envelope = {"schema_version": 1, "data": {"observations": [row]}, "usage": {}}
        original = json.dumps(envelope, sort_keys=True)
        client = Mock()
        client.prices.return_value = envelope
        payload, text, failed = await execute(client, SerialRunner(), "get_prices", {})
        self.assertFalse(failed)
        self.assertIs(payload, envelope)
        self.assertEqual(json.dumps(payload, sort_keys=True), original)
        client.prices.assert_called_once_with(None, limit=20, offset=0)
        for field, value in row.items():
            if field not in {"id", "product"}:
                self.assertIn("  " + field + ": " + json.dumps(value, ensure_ascii=True), text)
        self.assertLess(text.index("catalog_reference:"), text.index("currency:"))
        self.assertLess(text.index("comparison_eligible:"), text.index("currency:"))
        self.assertLess(len(text.encode()), MAX_TEXT_BYTES)
        self.assertIn("Automated observations are not human verification", text)
        self.assertNotIn('currency: "USD"', text)


if __name__ == "__main__":
    unittest.main()
