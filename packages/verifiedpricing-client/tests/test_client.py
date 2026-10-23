import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from verifiedpricing_client import Client, ClientError, __version__
from verifiedpricing_client.cli import main
from verifiedpricing_client import config

SNAPSHOT = "po_" + "a" * 64
SECOND = "po_" + "b" * 64
KEY = "vp_fixture_secret_not_real"
ENVELOPE = {"schema_version": 1, "data": {"observations": [{
    "id": SNAPSHOT, "product": "Fixture", "amount": "9.10", "currency": "USD",
    "source_url": "https://fixture.example/pricing", "observed_at": "2026-10-17T10:00:00Z",
    "provenance": "automated", "trust_label": "Automated pricing source; not human verified",
}], "next_offset": None}, "usage": {"daily_used": 1}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def respond(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.calls.append((self.command, self.path, self.headers.get("Authorization"), body))
        self.send_response(self.server.reply_status)
        for key, value in self.server.reply_headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(self.server.reply_body)


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.calls = []
        self.server.reply_status = 200
        self.server.reply_body = json.dumps(ENVELOPE).encode()
        self.server.reply_headers = {"Content-Type": "application/json"}
        self.client = Client(self.origin, KEY, allow_localhost=True)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "private" / "config.json"

    def cli(self, arguments, *, key=KEY, stdin=""):
        stdout, stderr = io.StringIO(), io.StringIO()
        env = {"VERIFIEDPRICING_API_KEY": key} if key is not None else {}
        with patch.dict(os.environ, env, clear=True), patch("sys.stdin", io.StringIO(stdin)):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = main(["--config", str(self.config_path), "--base-url", self.origin,
                               "--allow-localhost", *arguments])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_snapshot_parity_and_auth(self):
        self.assertEqual(self.client.price(SNAPSHOT), ENVELOPE)
        self.assertEqual(self.server.calls[0][:3], ("GET", "/api/v1/prices/" + SNAPSHOT, "Bearer " + KEY))

    def test_commands_map_to_versioned_routes(self):
        self.client.prices("product /?", limit=2, offset=4)
        self.client.search("notion", limit=5)
        self.client.history("product /?", offset=3)
        self.client.sources(SNAPSHOT)
        self.client.usage()
        paths = [call[1] for call in self.server.calls]
        self.assertIn("product_id=product+%2F%3F", paths[0])
        self.assertEqual(paths[1], "/api/v1/products?limit=5&offset=0&q=notion")
        self.assertEqual(paths[2], "/api/v1/products/product%20%2F%3F/history?limit=20&offset=3")
        self.assertEqual(paths[3], "/api/v1/prices/" + SNAPSHOT + "/sources")
        self.assertEqual(paths[4], "/api/v1/usage")

    def test_records_domain_validation_and_normalization(self):
        self.client.records("Fixture.Example.")
        self.assertEqual(self.server.calls[0][1], "/api/v1/records/fixture.example")
        for domain in ("127.0.0.1", "https://fixture.example", "fixture.example/path", "fixture.example?token=x",
                       "-bad.example", "bad-.example", "x.123", "fixture.example\n", "a" * 64 + ".example", None):
            with self.subTest(domain=domain), self.assertRaises(ClientError):
                self.client.records(domain)
        self.assertEqual(len(self.server.calls), 1)

    def test_records_json_preserves_every_qualification(self):
        fact = {"id": "vf_fixture_v1", "provenance": "human_reviewed", "currentness": "current",
                "verified_at": "2026-10-17T10:00:00Z", "freshness": "unknown", "source_url": None,
                "integrity": "missing", "badge_eligible": False, "comparison_eligible": False}
        payload = {"schema_version": 1, "usage": {"day": {"used": 1}}, "data": {
            "domain": "fixture.example", "name": "Fixture", "flagship_plan": "Pro", "facts": [fact], "history": []}}
        self.server.reply_body = json.dumps(payload).encode()
        code, out, error = self.cli(["records", "fixture.example", "--json"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(out), payload)

    def test_records_human_output_qualifies_stale_and_unknown_source(self):
        current = {"id": "vf_fixture_v2", "plan": "Pro", "attribute": "price", "value_json": {"amount": "9.10"},
                   "currentness": "current", "provenance": "review_metadata_incomplete", "freshness": "unknown",
                   "verified_at": None, "source_url": None, "integrity": "missing", "badge_eligible": False,
                   "comparison_eligible": False, "comparison_reason": "reviewed_fact_normalization_required"}
        historical = {**current, "id": "vf_fixture_v1", "currentness": "historical", "provenance": "human_reviewed",
                      "freshness": "stale", "verified_at": "2025-01-01T00:00:00Z", "captured_at": "2024-12-31T00:00:00Z",
                      "source_url": "https://fixture.example/pricing", "integrity": "intact"}
        self.server.reply_body = json.dumps({"schema_version": 1, "usage": {}, "data": {
            "domain": "fixture.example", "name": "Fixture", "flagship_plan": "Pro",
            "facts": [current], "history": [historical]}}).encode()
        code, out, error = self.cli(["records", "fixture.example"])
        self.assertEqual((code, error), (0, ""))
        for value in ("Current facts:", "Historical facts:", 'freshness: "stale"', "source_url: unknown",
                      "verified_at: unknown", "2025-01-01T00:00:00Z", "https://fixture.example/pricing",
                      'provenance: "review_metadata_incomplete"', "badge_eligible: false", "comparison_eligible: false"):
            self.assertIn(value, out)
        self.assertNotIn("comparison_eligible: true", out)

    def test_comparison_preserves_exact_decimal(self):
        code, out, error = self.cli(["compare", SNAPSHOT, SECOND, "--currency", "USD", "--market", "US",
            "--months", "24", "--seats", "4", "--as-of", "2026-10-17T10:00:00Z",
            "--usage-per-month", "0.10000001", "--usage-unit", "requests", "--json"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(out), ENVELOPE)
        request = json.loads(self.server.calls[0][3])
        self.assertEqual(request["scenario"]["usage_per_month"], "0.10000001")
        self.assertEqual(request["scenario"]["months"], 24)
        self.assertEqual(request["snapshot_ids"], [SNAPSHOT, SECOND])

    def test_json_before_and_after_command(self):
        for arguments in (["--json", "prices"], ["prices", "--json"]):
            code, out, error = self.cli(arguments)
            self.assertEqual((code, error, json.loads(out)), (0, "", ENVELOPE))

    def test_human_output_retains_source_date_and_trust(self):
        code, out, error = self.cli(["prices"])
        self.assertEqual((code, error), (0, ""))
        for value in (SNAPSHOT, "9.10", "https://fixture.example/pricing", "2026-10-17", "not human verified"):
            self.assertIn(value, out)
        self.assertNotIn(KEY, out)

    def test_catalog_reference_human_qualifications_and_json_passthrough(self):
        row = {
            "id": SNAPSHOT, "product": "Catalog fixture", "plan": "Annual",
            "amount": "9.10", "kind": "numeric", "currency": None, "unit": "seat/month",
            "billing_interval": "Billed annually", "commitment": {"months": 12},
            "market": None, "tax": "unknown", "conditions": "Annual prepayment; quote \u001b[31m is untrusted",
            "scope": {"basis": "catalog_reference"}, "seats": {"minimum": 3},
            "usage_tiers": [], "minimum_purchase": "3 seats", "discounts": None,
            "source_kind": "provider_retrieved_text", "source_url": "https://fixture.example/pricing",
            "observed_at": None, "retrieved_at": "2026-10-08T12:34:56Z", "verified_at": None,
            "currentness": "current", "freshness": "unknown", "provenance": "automated",
            "amount_supported": False, "comparison_eligible": False, "source_hash": None,
            "catalog_reference": {"catalog_id": "original100-reference-v1", "catalog_sha256": "b" * 64,
                "row_sha256": "c" * 64, "plan_index": 0, "currency_display": "$",
                "captured_at": None, "retrieved_at": "2026-10-08T12:34:56Z",
                "capture_qualification": "provider retrieval; upstream capture time unknown"},
        }
        payload = {"schema_version": 1, "data": {"observations": [row], "next_offset": None},
                   "usage": {"daily_used": 1}}
        self.server.reply_body = json.dumps(payload).encode()
        code, out, error = self.cli(["prices"])
        self.assertEqual((code, error), (0, ""))
        for field, value in row.items():
            if field not in {"id", "product"}:
                self.assertIn("  " + field + ": " + json.dumps(value, ensure_ascii=True), out)
        self.assertLess(out.index("catalog_reference:"), out.index("currency:"))
        self.assertLess(out.index("comparison_eligible:"), out.index("currency:"))
        self.assertNotIn("\u001b", out)
        self.assertNotIn('currency: "USD"', out)
        self.assertNotIn(KEY, out)
        code, out, error = self.cli(["prices", "--json"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(out, json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n")
        self.assertEqual(json.loads(out), payload)

    def test_redirect_is_not_followed(self):
        self.server.reply_status = 302
        self.server.reply_headers = {"Location": self.origin + "/stolen"}
        with self.assertRaises(ClientError) as caught:
            self.client.usage()
        self.assertEqual(caught.exception.message, "API redirect refused")
        self.assertEqual(len(self.server.calls), 1)

    def test_quota_is_structured_and_not_retried(self):
        self.server.reply_status = 429
        self.server.reply_headers = {"Retry-After": "60"}
        self.server.reply_body = b'{"detail":{"code":"quota_exceeded","message":"' + KEY.encode() + b'"}}'
        code, out, error = self.cli(["usage", "--json"])
        self.assertEqual((code, out), (4, ""))
        result = json.loads(error)["error"]
        self.assertEqual((result["code"], result["retry_after"]), ("quota_exceeded", "60"))
        self.assertNotIn(KEY, error)
        self.assertEqual(len(self.server.calls), 1)

    def test_echoed_credentials_never_output(self):
        for payload in ({**ENVELOPE, "data": {"token": KEY}},
                        {**ENVELOPE, "data": {"nested": [{KEY: "echo"}]}}):
            self.server.reply_body = json.dumps(payload).replace("vp_fixture", "\\u0076p_fixture").encode()
            code, out, error = self.cli(["usage", "--json"])
            self.assertEqual(code, 6)
            self.assertNotIn(KEY, out + error)

    def test_transport_error_never_echoes_exception_or_retries(self):
        with patch.object(self.client._opener, "open", side_effect=urllib.error.URLError(KEY)) as opened:
            with self.assertRaises(ClientError) as caught:
                self.client.usage()
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(caught.exception.code, "transport")
        self.assertNotIn(KEY, str(caught.exception))

    def test_human_comparison_includes_exclusions_and_calculation(self):
        payload = {"schema_version": 1, "usage": {"day": {"used": 2}}, "data": {
            "status": "not_comparable", "reasons": ["tax_basis_mismatch"],
            "prices": [{"snapshot_id": SNAPSHOT, "status": "calculated",
                        "source_url": "https://fixture.example/pricing", "calculation": {
                            "effective_monthly_cost": "9.10"}}]}}
        self.server.reply_body = json.dumps(payload).encode()
        code, out, error = self.cli(["usage"])
        self.assertEqual((code, error), (0, ""))
        for value in ("tax_basis_mismatch", "9.10", "https://fixture.example/pricing", "Usage:"):
            self.assertIn(value, out)

    def test_status_exit_codes_and_secret_safe_errors(self):
        for status, expected in ((401, 3), (403, 3), (404, 5), (500, 6)):
            self.server.reply_status = status
            self.server.reply_body = KEY.encode()
            code, out, error = self.cli(["usage", "--json"])
            self.assertEqual((code, out), (expected, ""))
            self.assertNotIn(KEY, error)

    def test_response_size_schema_and_json_bounds(self):
        for body in (b"x" * (512 * 1024 + 1), b"not json", b'{"schema_version":2}',
                     b'{"schema_version":1,"data":{},"usage":{},"n":NaN}'):
            self.server.reply_body = body
            with self.assertRaises(ClientError):
                self.client.usage()

    def test_no_request_for_invalid_input(self):
        for args in (["prices", "--limit", "51"], ["prices", "--offset", "10001"],
                     ["price", "../../secret"], ["--json", KEY],
                     ["compare", SNAPSHOT, SECOND, "--currency", "USD", "--market", "US", "--as-of", "2026-10-17"]):
            code, out, error = self.cli(args)
            self.assertEqual(code, 2)
            self.assertNotIn(KEY, out + error)
        self.assertEqual(self.server.calls, [])

    def test_origin_and_timeout_security(self):
        for value in ("http://example.com", self.origin, "https://u:secret@example.com",
                      "https://example.com/api", "https://example.com?token=secret", "https://example.com\n"):
            with self.assertRaises(ClientError):
                Client(value)
        for timeout in (0, 61, float("nan"), float("inf")):
            with self.assertRaises(ClientError):
                Client(timeout=timeout)
        with self.assertRaises(ClientError):
            Client(api_key="key\r\nheader")

    def test_anonymous_does_not_send_auth(self):
        Client(self.origin, allow_localhost=True).prices()
        self.assertIsNone(self.server.calls[0][2])

    def test_configuration_atomic_and_private(self):
        code, out, error = self.cli(["configure", "--key-stdin", "--json"], key=None, stdin=KEY + "\n")
        self.assertEqual((code, error), (0, ""))
        self.assertNotIn(KEY, out)
        self.assertEqual(stat.S_IMODE(self.config_path.stat().st_mode), 0o600)
        self.assertEqual(config.load(self.config_path)["api_key"], KEY)
        config.save(self.config_path, api_key="vp_rotated_fixture", base_url="https://verifiedpricing.com")
        self.assertEqual(config.load(self.config_path)["api_key"], "vp_rotated_fixture")
        self.assertEqual(list(self.config_path.parent.iterdir()), [self.config_path])
        self.assertEqual(self.server.calls, [])

    def test_config_rejects_permissions_symlinks_and_malformed_data(self):
        config.save(self.config_path, api_key=KEY, base_url="https://verifiedpricing.com")
        self.config_path.chmod(0o644)
        with self.assertRaises(ClientError):
            config.load(self.config_path)
        self.config_path.chmod(0o600)
        linked = self.config_path.parent / "linked.json"
        linked.symlink_to(self.config_path)
        with self.assertRaises(ClientError):
            config.load(linked)
        with self.assertRaises(ClientError):
            config.save(linked, api_key=KEY, base_url="https://verifiedpricing.com")
        self.config_path.write_text(KEY)
        with self.assertRaises(ClientError) as caught:
            config.load(self.config_path)
        self.assertNotIn(KEY, str(caught.exception))

    def test_private_config_auth_and_environment_precedence(self):
        config.save(self.config_path, api_key="vp_saved_fixture", base_url=self.origin, allow_localhost=True)
        self.assertEqual(self.cli(["usage"], key=None)[0], 0)
        self.assertEqual(self.server.calls[-1][2], "Bearer vp_saved_fixture")
        self.config_path.chmod(0o644)
        self.assertEqual(self.cli(["usage"])[0], 0)
        self.assertEqual(self.server.calls[-1][2], "Bearer " + KEY)

    def test_help_and_version_do_not_load_configuration(self):
        for flag in ("--help", "--version"):
            output = io.StringIO()
            with patch("verifiedpricing_client.config.load", side_effect=AssertionError("must not load")):
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as caught:
                    main([flag])
            self.assertEqual(caught.exception.code, 0)
            if flag == "--version":
                self.assertIn(__version__, output.getvalue())


if __name__ == "__main__":
    unittest.main()
