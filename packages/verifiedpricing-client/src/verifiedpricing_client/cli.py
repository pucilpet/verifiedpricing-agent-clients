"""Stable JSON envelopes and concise, source-preserving terminal output."""

import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .client import COVERAGE_CATEGORIES, Client, ClientError
from . import config


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's usual message may echo accidental credential arguments.
        raise ClientError("input", "Invalid arguments; use --help for usage")


class SelectAction(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        current = getattr(namespace, self.dest, None) or []
        if len(current) >= 3 or len(value) > 199:
            raise ClientError("input", "Provide at most three bounded PRODUCT_ID=SNAPSHOT_ID selections")
        setattr(namespace, self.dest, [*current, value])


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Stable JSON output")
    common.add_argument("--base-url", default=argparse.SUPPRESS, help="HTTPS API origin")
    common.add_argument("--config", type=Path, default=argparse.SUPPRESS, help="Private configuration path")
    common.add_argument("--allow-localhost", action="store_true", default=argparse.SUPPRESS, help="Allow HTTP only for localhost development")
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS, help="Network timeout, 0 < seconds <= 60")
    root = Parser(prog="verifiedpricing", parents=[common], description="Dated source-backed pricing. Automated observations are not human verification.")
    root.add_argument("--version", action="version", version="%(prog)s " + __version__)
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("prices", "price", "compare", "competitors", "usage", "search", "history", "sources", "records",
                 "coverage-request", "coverage-status", "configure"):
        child = commands.add_parser(name, parents=[common])
        if name in {"prices", "history", "search"}:
            child.add_argument("--limit", type=int, default=20)
            child.add_argument("--offset", type=int, default=0)
        if name == "prices":
            child.add_argument("--product-id")
        elif name in {"price", "sources"}:
            child.add_argument("snapshot")
        elif name == "history":
            child.add_argument("product_id")
        elif name == "search":
            child.add_argument("query")
        elif name == "records":
            child.add_argument("domain", help="Domain for dated reviewed facts and history")
        elif name == "coverage-request":
            target = child.add_mutually_exclusive_group(required=True)
            target.add_argument("--product-id", help="Existing product ID")
            target.add_argument("--domain", help="Canonical lowercase product domain")
            child.add_argument("--category", choices=COVERAGE_CATEGORIES, help="Required for domain research")
            child.add_argument("--product-name", help="Optional product name for research")
            child.add_argument("--consent", action="store_true", required=True,
                               help="Explicitly queue pricing research using the shared crawl allowance")
        elif name == "coverage-status":
            child.add_argument("request_id", help="Your pricing coverage request ID")
        elif name in {"compare", "competitors"}:
            if name == "compare":
                child.add_argument("snapshots", nargs="+", help="Two or three pinned snapshot IDs")
            else:
                seed = child.add_mutually_exclusive_group(required=True)
                seed.add_argument("--product-id", help="Seed product ID")
                seed.add_argument("--domain", help="Canonical lowercase seed domain")
                child.add_argument("--limit", type=int, choices=(2, 3), default=3, help="Total products including the seed")
                child.add_argument("--competitor-product-id", help="Restrict to one exact published qualified competitor product ID")
                child.add_argument("--select", action=SelectAction, default=[], metavar="PRODUCT_ID=SNAPSHOT_ID")
            child.add_argument("--currency", required=True)
            child.add_argument("--market", required=True)
            child.add_argument("--months", type=int, default=12)
            child.add_argument("--seats", type=int, default=1)
            child.add_argument("--usage-per-month")
            child.add_argument("--usage-unit")
            child.add_argument("--as-of", required=True, help="ISO-8601 timestamp with timezone")
        elif name == "configure":
            child.add_argument("--key-stdin", action="store_true", help="Read an existing VP API key from stdin; otherwise use VERIFIEDPRICING_API_KEY")
    return root


def scenario(args):
    try:
        instant = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if instant.utcoffset() is None or not re.fullmatch(r"[A-Z]{3}", args.currency):
            raise ValueError()
        if not 2 <= len(args.market) <= 64 or any(ord(c) < 32 for c in args.market):
            raise ValueError()
        if not 1 <= args.months <= 120 or not 1 <= args.seats <= 1000000:
            raise ValueError()
        usage = args.usage_per_month
        if usage is not None:
            number = Decimal(usage)
            if not number.is_finite() or number < 0 or len(usage) > 64:
                raise ValueError()
        if args.usage_unit is not None and not 1 <= len(args.usage_unit) <= 64:
            raise ValueError()
    except (ValueError, InvalidOperation, OverflowError):
        raise ClientError("input", "Invalid scenario; specify timezone, ISO currency and bounded nonnegative quantities") from None
    result = {"currency": args.currency, "market": args.market, "months": args.months,
              "seats": args.seats, "as_of": instant.isoformat()}
    if usage is not None:
        result["usage_per_month"] = usage
    if args.usage_unit is not None:
        result["usage_unit"] = args.usage_unit
    return result


def human(payload):
    data = payload["data"]
    if isinstance(data.get("id"), str) and re.fullmatch(r"cr_[0-9a-f]{32}", data["id"]):
        ordered = [name for name in ("id", "status", "domain", "product_id", "category", "product_name",
                                    "reason", "revision", "snapshot_id", "record_url") if name in data]
        ordered.extend(sorted(set(data) - set(ordered)))
        lines = [name + ": " + json.dumps(data[name], sort_keys=True, ensure_ascii=True) for name in ordered]
        if payload.get("usage"):
            lines.append("Usage: " + json.dumps(payload["usage"], sort_keys=True, ensure_ascii=True))
        return "\n".join(lines)
    if "competitors" in data or "seed" in data:
        # Render top-level service fields without guessing nested discovery/coverage schemas.
        ordered = [name for name in ("status", "reason", "seed", "competitors", "discovery", "comparison", "selection_policy") if name in data]
        ordered.extend(sorted(set(data) - set(ordered)))
        lines = [name + ": " + json.dumps(data[name], sort_keys=True, ensure_ascii=True) for name in ordered]
        if payload.get("usage"):
            lines.append("Usage: " + json.dumps(payload["usage"], sort_keys=True, ensure_ascii=True))
        return "\n".join(lines)
    if "facts" in data and "history" in data:
        return human_records(payload)
    rows = data.get("observations", data.get("prices", data.get("products")))
    if not isinstance(rows, list):
        rows = [data]
    if not rows:
        return "No matching published data."
    lines = []
    if "prices" in data:
        for field in ("comparison_id", "status", "reasons", "scenario"):
            if field in data:
                lines.append(field + ": " + json.dumps(data[field], sort_keys=True, ensure_ascii=True))
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get("product") or row.get("product_id") or row.get("id") or "Usage / source"
        identifier = row.get("snapshot_id") or row.get("id")
        safe_title = json.dumps(str(title), ensure_ascii=True)[1:-1]
        safe_id = json.dumps(str(identifier), ensure_ascii=True)[1:-1]
        lines.append(safe_title + (" | " + safe_id if identifier and title != identifier else ""))
        for field in ("plan", "kind", "amount", "catalog_reference", "amount_supported", "comparison_eligible",
                      "currency", "currency_display", "unit", "billing_interval", "commitment", "market", "tax",
                      "conditions", "scope", "seats", "usage_tiers", "minimum_purchase", "discounts",
                      "total_cost", "effective_monthly_cost", "trust_label", "provenance", "source_kind",
                      "currentness", "freshness", "integrity", "dispute", "observed_at", "retrieved_at", "verified_at", "source_url", "source_hash", "quote",
                      "status", "reasons", "calculation"):
            if field in row:
                lines.append("  " + field + ": " + json.dumps(row[field], ensure_ascii=True))
        if len(rows) == 1 and not any(field in row for field in ("source_url", "product_id", "product")):
            lines.append("  " + json.dumps(row, sort_keys=True, ensure_ascii=True))
    if data.get("next_offset") is not None:
        lines.append("Next offset: " + str(data["next_offset"]))
    if payload.get("usage"):
        lines.append("Usage: " + json.dumps(payload["usage"], sort_keys=True, ensure_ascii=True))
    return "\n".join(lines)


def human_records(payload):
    data = payload["data"]
    def display(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=True)
    lines = ["Reviewed record: " + display(data.get("domain")),
             "Name: " + display(data.get("name")),
             "Flagship plan: " + display(data.get("flagship_plan"))]
    for section in ("facts", "history"):
        rows = data.get(section)
        lines.append("Current facts:" if section == "facts" else "Historical facts:")
        if not isinstance(rows, list) or not rows:
            lines.append("  No published facts.")
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            lines.append("  " + display(row.get("id")) + " | " + display(row.get("plan"))
                         + " | " + display(row.get("attribute")) + ": " + display(row.get("value_json")))
            # Missing qualification stays unknown; it must never become a positive badge.
            for field in ("currentness", "provenance", "freshness", "integrity", "evidence_status",
                          "badge_eligible", "comparison_eligible", "comparison_reason", "scope", "region"):
                value = row.get(field)
                lines.append("    " + field + ": " + ("unknown" if value is None else display(value)))
            for field in ("verified_at", "captured_at", "effective_from", "effective_to", "source_url", "source_hash"):
                value = row.get(field)
                lines.append("    " + field + ": " + (display(value) if value else "unknown"))
    if payload.get("usage"):
        lines.append("Usage: " + display(payload["usage"]))
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in argv
    try:
        args = parser().parse_args(argv)
        json_output = getattr(args, "json", False)
        path = getattr(args, "config", None) or config.default_path()
        # An explicit env key can be used without touching any credential file.
        env_key = os.environ.get("VERIFIEDPRICING_API_KEY")
        saved = {} if env_key is not None or args.command == "configure" else config.load(path)
        base = getattr(args, "base_url", None) or saved.get("base_url", "https://verifiedpricing.com")
        local = getattr(args, "allow_localhost", False)
        if args.command == "configure":
            key = sys.stdin.read(4098).strip() if args.key_stdin else env_key
            if not key:
                raise ClientError("configuration", "Provide an existing VP key through stdin or VERIFIEDPRICING_API_KEY")
            config.save(path, api_key=key, base_url=base, allow_localhost=local)
            payload = {"schema_version": 1, "data": {"configured": True}, "usage": {}}
        else:
            client = Client(base, env_key if env_key is not None else saved.get("api_key"),
                            allow_localhost=local, timeout=getattr(args, "timeout", 15))
            if args.command == "prices":
                payload = client.prices(args.product_id, limit=args.limit, offset=args.offset)
            elif args.command == "price":
                payload = client.price(args.snapshot)
            elif args.command == "compare":
                payload = client.compare(args.snapshots, scenario(args))
            elif args.command == "competitors":
                selections = {}
                for item in args.select:
                    if "=" not in item:
                        raise ClientError("input", "Each selection must be PRODUCT_ID=SNAPSHOT_ID")
                    product_id, snapshot = item.split("=", 1)
                    if product_id in selections:
                        raise ClientError("input", "Select each product at most once")
                    selections[product_id] = snapshot
                payload = client.competitor_prices(scenario=scenario(args), product_id=args.product_id,
                    domain=args.domain, limit=args.limit, selections=selections if args.select else None,
                    competitor_product_id=args.competitor_product_id)
            elif args.command == "search":
                payload = client.search(args.query, limit=args.limit, offset=args.offset)
            elif args.command == "history":
                payload = client.history(args.product_id, limit=args.limit, offset=args.offset)
            elif args.command == "sources":
                payload = client.sources(args.snapshot)
            elif args.command == "records":
                payload = client.records(args.domain)
            elif args.command == "coverage-request":
                payload = client.request_price_coverage(consent=args.consent, product_id=args.product_id,
                    domain=args.domain, category=args.category, product_name=args.product_name)
            elif args.command == "coverage-status":
                payload = client.price_coverage_request(args.request_id)
            else:
                payload = client.usage()
        print(json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False) if json_output else human(payload))
        return 0
    except (OSError, ClientError) as exc:
        if not isinstance(exc, ClientError):
            exc = ClientError("local_io", "Local configuration or network I/O failed")
        if json_output:
            print(json.dumps({"schema_version": 1, "error": exc.as_dict()}, sort_keys=True), file=sys.stderr)
        else:
            suffix = " (Retry-After: " + exc.retry_after + ")" if exc.retry_after else ""
            print(exc.message + suffix, file=sys.stderr)
        return (2 if exc.code in {"input", "configuration", "local_io"} else
                3 if exc.status in (401, 403) else 4 if exc.status == 429 else
                5 if exc.status == 404 else 6)
