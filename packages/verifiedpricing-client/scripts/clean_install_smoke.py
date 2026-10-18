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
                        "check installed module location, console version/help", "loopback bearer JSON/human usage smoke"]}
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
        run([str(python), "-c", "import pathlib, sys, verifiedpricing_client as c; assert pathlib.Path(c.__file__).is_relative_to(pathlib.Path(sys.prefix)); assert c.__version__ == '0.1.0'"])
        version = run([str(command), "--version"]).strip()
        if version != "verifiedpricing 0.1.0" or "records" not in run([str(command), "--help"]):
            raise RuntimeError("Installed console metadata does not match")
        calls = []
        payload = {"schema_version": 1, "data": {"account_budget": "shared_across_transports"},
                   "usage": {"day": {"used": 0, "limit": 1000}}}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                calls.append((self.path, self.headers.get("Authorization")))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
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
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        receipt.update(executed=True, version=version, loopback_requests=len(calls), passed=True)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
