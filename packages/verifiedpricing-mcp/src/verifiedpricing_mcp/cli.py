"""Local stdio launcher; no hosted OAuth or credentials in tool arguments."""

import argparse
import asyncio
import importlib.metadata
import logging
import os
from pathlib import Path
import sys

from . import __version__


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid launch arguments; use --help.\n")


def main(argv=None):
    parser = Parser(prog="verifiedpricing-mcp", description="Bounded local MCP stdio gateway; requires a user's own VP REST credential or anonymous service support")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--base-url", help="HTTPS API origin, never supplied through a tool")
    parser.add_argument("--config", type=Path, help="Owned private 0600 client configuration")
    parser.add_argument("--allow-localhost", action="store_true", help="Explicit HTTP localhost development mode")
    args = parser.parse_args(argv)
    # SDK diagnostics can contain untrusted request values; this dedicated process emits only generic errors.
    logging.disable(logging.CRITICAL)
    try:
        if os.name != "posix":
            raise RuntimeError()
        if importlib.metadata.version("mcp") != "2.3.0" or importlib.metadata.version("verifiedpricing-client") != "0.1.3":
            raise RuntimeError()
        from verifiedpricing_client import Client, config
        from .server import serve
        from .transport import claim_stdio
        key = os.environ.get("VERIFIEDPRICING_API_KEY")
        saved = {} if key is not None else config.load(args.config or config.default_path())
        key = key if key is not None else saved.get("api_key")
        origin = args.base_url or saved.get("base_url", "https://verifiedpricing.com")
        client = Client(origin, key, allow_localhost=args.allow_localhost, timeout=15)
        with claim_stdio() as (input_fd, output_fd):
            asyncio.run(serve(client, input_fd, output_fd, secret=key))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        sys.stderr.write("VerifiedPricing MCP could not complete safely; check installation and private configuration.\n")
        return 2
