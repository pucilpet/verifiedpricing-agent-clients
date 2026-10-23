"""Prepare an offline wheel smoke; execution still requires prior resource admission."""

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

MAX_WHEEL_BYTES = 16 * 1024 * 1024
FIXTURE_KEY = "vp_clean_install_fixture_not_real"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Previously built, reviewed wheel artifact")
    parser.add_argument("--execute", action="store_true", help="Run after coordinator resource admission; otherwise print plan only")
    args = parser.parse_args(argv)
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl" or wheel.stat().st_size > MAX_WHEEL_BYTES:
        parser.error("Provide a wheel artifact no larger than 16 MiB")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    receipt = {"artifact_sha256": digest, "executed": False,
               "plan": ["create isolated temporary venv outside checkout", "offline no-dependency wheel install",
                        "check installed module location, console version/help", "loopback bearer JSON/human usage and catalog qualification smoke"]}
    if not args.execute:
        print(json.dumps(receipt, sort_keys=True))
        return 0
    with tempfile.TemporaryDirectory(prefix="vp-client-clean-install-") as temporary:
        root = Path(temporary)
        environment = dict(os.environ)
        for name in ("PYTHONPATH", "PYTHONHOME", "VERIFIEDPRICING_API_KEY"):
            environment.pop(name, None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        def run(command, **kwargs):
            return subprocess.run(command, cwd=root, env=environment, check=True,
                                  text=True, capture_output=True, timeout=90, **kwargs).stdout
        run([sys.executable, "-m", "venv", str(root / "venv")])
        python = root / "venv/bin/python"
        command = root / "venv/bin/verifiedpricing"
        run([str(python), "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", str(wheel)])
        run([str(python), "-c", "import pathlib, sys, verifiedpricing_client as c; assert pathlib.Path(c.__file__).is_relative_to(pathlib.Path(sys.prefix)); assert c.__version__ == '0.1.3'"])
        version = run([str(command), "--version"]).strip()
        help_text = run([str(command), "--help"])
        if version != "verifiedpricing 0.1.3" or any(name not in help_text for name in ("records", "coverage-request", "coverage-status")):
            raise RuntimeError("Installed console metadata does not match")
        calls = []
        payload = {"schema_version": 1, "data": {"account_budget": "shared_across_transports"},
                   "usage": {"day": {"used": 0, "limit": 1000}}}
        request_id = "cr_" + "a" * 32
        coverage = {"schema_version": 1, "data": {"id": request_id, "status": "queued",
                    "domain": "product.example", "canonical_domain": None, "category": "crm", "revision": 0},
                    "usage": {"day": {"used": 1, "limit": 1000}}}
        catalog_row = {"id": "po_" + "b" * 64, "product": "Catalog fixture", "amount": "9.10",
                       "currency": None, "amount_supported": False, "comparison_eligible": False,
                       "billing_interval": "Billed annually", "conditions": "Prepay 12 months; \u001b[31m untrusted",
                       "source_kind": "provider_retrieved_text", "observed_at": None,
                       "retrieved_at": "2026-10-08T12:34:56Z", "verified_at": None,
                       "catalog_reference": {"catalog_id": "fixture", "currency_display": "$",
                           "capture_qualification": "provider retrieval; upstream capture time unknown"}}
        catalog = {"schema_version": 1, "data": {"observations": [catalog_row]}, "usage": {}}
        prices_path = "/api/v1/prices?limit=20&offset=0"
        submitted = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                calls.append((self.path, self.headers.get("Authorization")))
                if self.path not in ("/api/v1/usage", "/api/v1/coverage-requests/" + request_id, prices_path):
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(catalog if self.path == prices_path else coverage if self.path.endswith(request_id) else payload).encode())

            def do_POST(self):
                calls.append((self.path, self.headers.get("Authorization")))
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != "/api/v1/coverage-requests" or not 0 < length <= 16384:
                    self.send_error(422)
                    return
                body = json.loads(self.rfile.read(length))
                if body != {"domain": "product.example", "category": "crm", "consent": True}:
                    self.send_error(422)
                    return
                submitted.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(coverage).encode())
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            environment["VERIFIEDPRICING_API_KEY"] = FIXTURE_KEY
            arguments = [str(command), "--base-url", "http://127.0.0.1:" + str(server.server_port),
                         "--allow-localhost", "--config", str(root / "unused-config.json"), "usage"]
            if json.loads(run([*arguments, "--json"])) != payload:
                raise RuntimeError("Installed JSON response differs from fixture")
            if "Usage:" not in run(arguments):
                raise RuntimeError("Installed human output omits shared budget")
            if calls != [("/api/v1/usage", "Bearer " + FIXTURE_KEY)] * 2:
                raise RuntimeError("Installed request routing or authentication differs")
            prefix = arguments[:-1]
            if json.loads(run([*prefix, "prices", "--json"])) != catalog:
                raise RuntimeError("Installed catalog JSON differs from fixture")
            catalog_text = run([*prefix, "prices"])
            for field, value in catalog_row.items():
                if field not in {"id", "product"} and "  " + field + ": " + json.dumps(value, ensure_ascii=True) not in catalog_text:
                    raise RuntimeError("Installed human output omits catalog qualification: " + field)
            if "\u001b" in catalog_text or 'currency: "USD"' in catalog_text:
                raise RuntimeError("Installed human output changes catalog trust or escaping")
            research = [*prefix, "coverage-request", "--domain", "product.example", "--category", "crm", "--consent", "--json"]
            if json.loads(run(research)) != coverage:
                raise RuntimeError("Installed coverage request differs from fixture")
            if json.loads(run([*prefix, "coverage-status", request_id, "--json"])) != coverage:
                raise RuntimeError("Installed coverage status differs from fixture")
            if json.loads(run(research)) != coverage or len(submitted) != 2:
                raise RuntimeError("Installed repeated coverage request differs")
            expected = [("/api/v1/usage", "Bearer " + FIXTURE_KEY)] * 2 + [(prices_path, "Bearer " + FIXTURE_KEY)] * 2 + [
                ("/api/v1/coverage-requests", "Bearer " + FIXTURE_KEY),
                ("/api/v1/coverage-requests/" + request_id, "Bearer " + FIXTURE_KEY),
                ("/api/v1/coverage-requests", "Bearer " + FIXTURE_KEY)]
            if calls != expected:
                raise RuntimeError("Installed coverage routing, credentials or request count differs")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        receipt.update(executed=True, version=version, loopback_requests=len(calls), passed=True)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
