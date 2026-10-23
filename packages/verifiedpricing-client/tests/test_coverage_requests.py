"""Coverage demand crosses the wire only after explicit opt-in."""

import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

from verifiedpricing_client import Client, ClientError
from verifiedpricing_client.cli import human, main

REQUEST_ID = "cr_" + "a" * 32
PAYLOAD = {"schema_version": 1, "usage": {"day": {"used": 1}}, "data": {
    "id": REQUEST_ID, "status": "queued", "domain": "product.example", "product_id": None,
    "category": "social media", "product_name": "Product", "reason": None,
    "revision": 1, "snapshot_id": None, "record_url": None}}


class Response(io.BytesIO):
    def __init__(self, payload=PAYLOAD, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status
        self.headers = {"Content-Type": "application/json"}


class CoverageRequestClientTests(unittest.TestCase):
    def setUp(self):
        self.client = Client(api_key="vp_test_coverage_not_real")
        p = patch.object(self.client._opener, "open", side_effect=lambda *a, **kw: Response())
        self.opened = p.start()
        self.addCleanup(p.stop)

    def cli(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"VERIFIEDPRICING_API_KEY": "vp_test_coverage_not_real"}, clear=True):
            with patch("verifiedpricing_client.cli.Client", return_value=self.client):
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    code = main(arguments)
        return code, output.getvalue(), error.getvalue()

    def test_domain_request_preserves_hints_consent_and_envelope(self):
        result = self.client.request_price_coverage(consent=True, domain="product.example",
            category="social media", product_name="Product")
        request = self.opened.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "https://verifiedpricing.com/api/v1/coverage-requests")
        self.assertEqual(json.loads(request.data), {"consent": True, "domain": "product.example",
            "category": "social media", "product_name": "Product"})
        self.assertEqual(result, PAYLOAD)
        self.assertEqual(self.opened.call_count, 1)

    def test_product_id_request_does_not_invent_a_domain_or_category(self):
        self.client.request_price_coverage(consent=True, product_id="product:existing.example")
        self.assertEqual(json.loads(self.opened.call_args.args[0].data),
                         {"consent": True, "product_id": "product:existing.example"})

    def test_known_domain_request_preserves_absent_category_for_replay(self):
        self.client.request_price_coverage(consent=True, domain="product.example")
        self.assertEqual(json.loads(self.opened.call_args.args[0].data),
                         {"consent": True, "domain": "product.example"})

    def test_cli_known_domain_preserves_absent_category(self):
        code, output, error = self.cli(["coverage-request", "--domain", "product.example", "--consent", "--json"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output), PAYLOAD)
        self.assertEqual(json.loads(self.opened.call_args.args[0].data),
                         {"consent": True, "domain": "product.example"})

    def test_missing_or_coerced_consent_never_issues_http(self):
        for consent in (False, None, 1, "true", [], {}):
            with self.subTest(consent=consent), self.assertRaises(ClientError):
                self.client.request_price_coverage(consent=consent, product_id="existing")
        self.opened.assert_not_called()

    def test_invalid_target_and_research_hints_never_issue_http(self):
        invalid = [{}, {"product_id": "p", "domain": "product.example"}, {"product_id": "bad/id"},
                   {"product_id": True},
                   {"domain": "https://product.example/pricing", "category": "seo"},
                   {"domain": "Product.example", "category": "seo"},
                   {"domain": "127.0.0.1", "category": "seo"},
                   {"domain": "product.example", "category": "unknown"},
                   {"domain": "product.example", "category": ["seo"]}]
        invalid.extend({"product_id": "p", "product_name": value}
                       for value in ("", " ", "x" * 121, "Product\nname", True))
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ClientError):
                self.client.request_price_coverage(consent=True, **arguments)
        self.opened.assert_not_called()

    def test_status_is_a_single_get_and_preserves_account_request(self):
        self.assertEqual(self.client.price_coverage_request(REQUEST_ID), PAYLOAD)
        request = self.opened.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url,
                         "https://verifiedpricing.com/api/v1/coverage-requests/" + REQUEST_ID)
        self.assertIsNone(request.data)
        self.assertEqual(self.opened.call_count, 1)

    def test_status_rejects_paths_and_non_request_ids_before_http(self):
        for value in ("", "../prices", "cr_" + "a" * 31, "cr_" + "A" * 32, True, None, "po_" + "a" * 64):
            with self.subTest(value=value), self.assertRaises(ClientError):
                self.client.price_coverage_request(value)
        self.opened.assert_not_called()

    def test_cli_requires_consent_and_explicit_target(self):
        for arguments in (["coverage-request", "--domain", "product.example", "--category", "seo"],
                          ["coverage-request", "--consent"]):
            with self.subTest(arguments=arguments):
                code, output, error = self.cli([*arguments, "--json"])
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertEqual(json.loads(error)["error"]["code"], "input")
        self.opened.assert_not_called()

    def test_cli_request_and_status_preserve_exact_json(self):
        arguments = ["coverage-request", "--domain", "product.example", "--category", "social media",
                     "--product-name", "Product", "--consent", "--json"]
        code, output, error = self.cli(arguments)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output), PAYLOAD)
        code, output, error = self.cli(["coverage-status", REQUEST_ID, "--json"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output), PAYLOAD)

    def test_human_status_includes_request_identity_hints_and_held_reason(self):
        result = {**PAYLOAD, "data": {**PAYLOAD["data"], "status": "held",
                                    "reason": "qualification_requires_review", "revision": 2}}
        text = human(result)
        for expected in (REQUEST_ID, 'status: "held"', 'domain: "product.example"',
                         'category: "social media"', 'reason: "qualification_requires_review"',
                         "revision: 2", "snapshot_id: null", "Usage:"):
            self.assertIn(expected, text)

    def test_missing_read_does_not_post_or_retry(self):
        self.opened.side_effect = lambda *a, **kw: Response({"detail": "missing"}, 404)
        with self.assertRaises(ClientError) as stopped:
            self.client.price("po_" + "a" * 64)
        self.assertEqual(stopped.exception.status, 404)
        self.assertEqual(self.opened.call_count, 1)
        self.assertEqual(self.opened.call_args.args[0].method, "GET")

    def test_lost_post_response_is_not_implicitly_retried(self):
        self.opened.side_effect = TimeoutError("unknown remote result")
        with self.assertRaises(ClientError) as stopped:
            self.client.request_price_coverage(consent=True, product_id="existing")
        self.assertEqual(stopped.exception.code, "transport")
        self.assertEqual(self.opened.call_count, 1)


if __name__ == "__main__":
    unittest.main()
