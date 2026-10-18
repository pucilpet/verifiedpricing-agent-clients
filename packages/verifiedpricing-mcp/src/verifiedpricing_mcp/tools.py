"""Fixed tools: credentials, origins and raw price claims are never tool inputs."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re

from verifiedpricing_client import ClientError
from verifiedpricing_client.cli import human

from .runner import Busy, DeadlineExceeded, OperationFailed

MAX_TEXT_BYTES = 8192
MAX_TOOL_BYTES = 640 * 1024
_SNAPSHOT = {"type": "string", "pattern": "^po_[0-9a-f]{64}$"}
_IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 128}
_PRODUCT_ID = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": "^[A-Za-z0-9:_.-]+$"}
_PAGE = {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
         "offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0}}


def schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False}


SCENARIO = schema({
    "as_of": {"type": "string", "maxLength": 64, "description": "ISO-8601 timestamp with explicit timezone"},
    "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
    "market": {"type": "string", "minLength": 2, "maxLength": 64},
    "months": {"type": "integer", "minimum": 1, "maximum": 120, "default": 12},
    "seats": {"type": "integer", "minimum": 1, "maximum": 1000000, "default": 1},
    "usage_per_month": {"type": "string", "maxLength": 32, "description": "Nonnegative exact decimal, at most 18 digits and 8 fractional digits"},
    "usage_unit": {"type": "string", "minLength": 1, "maxLength": 64},
    "allow_stale": {"type": "boolean", "default": False},
}, ("as_of", "currency", "market"))

COMPETITORS = schema({
    "product_id": _PRODUCT_ID,
    "domain": {"type": "string", "minLength": 3, "maxLength": 253,
               "pattern": r"^(?=.{1,253}$)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"},
    "scenario": SCENARIO,
    "limit": {"type": "integer", "minimum": 2, "maximum": 3, "default": 3,
              "description": "Total product count including the seed; two or three"},
    "selections": {"type": "object", "maxProperties": 3, "propertyNames": _PRODUCT_ID,
                   "additionalProperties": _SNAPSHOT},
}, ("scenario",))
COMPETITORS["oneOf"] = [{"required": ["product_id"]}, {"required": ["domain"]}]

TOOLS = {
    "search_products": ("Search bounded published products, not a completeness guarantee.", schema({"query": {"type": "string", "minLength": 1, "maxLength": 100}, **_PAGE}, ("query",))),
    "get_prices": ("List published automated snapshots with source dates and explicit qualifications.", schema({"product_id": _IDENTIFIER, **_PAGE})),
    "get_price": ("Read one pinned pricing snapshot; automated does not mean human verified.", schema({"snapshot_id": _SNAPSHOT}, ("snapshot_id",))),
    "compare_prices": ("Compare two or three pinned observations without FX, guessed context or verification upgrades.", schema({"snapshot_ids": {"type": "array", "items": _SNAPSHOT, "minItems": 2, "maxItems": 3, "uniqueItems": True}, "scenario": SCENARIO}, ("snapshot_ids", "scenario"))),
    "get_competitor_prices": ("Read retained competitor-pricing coverage for exactly one seed product or domain. Total product limit includes the seed; no crawl or live LinkCensus query occurs. Partial coverage and comparison exclusions remain explicit.", COMPETITORS),
    "get_price_history": ("Read bounded dated published observation versions.", schema({"product_id": _IDENTIFIER, **_PAGE}, ("product_id",))),
    "get_sources": ("Read retained source metadata and integrity qualification for a snapshot.", schema({"snapshot_id": _SNAPSHOT}, ("snapshot_id",))),
    "get_reviewed_records": ("Read recorded human-review qualifications per fact; stale, unknown, badge and comparison eligibility remain explicit.", schema({"domain": {"type": "string", "minLength": 3, "maxLength": 253}}, ("domain",))),
    "get_usage": ("Read shared account budgets without granting a new allowance.", schema()),
}


class InvalidInput(Exception):
    pass


def validate(value, rule):
    kind = rule["type"]
    if kind == "object":
        if (not isinstance(value, dict) or len(value) > rule.get("maxProperties", 100)
                or set(rule.get("required", ())) - value.keys()):
            raise InvalidInput()
        if "oneOf" in rule and sum(set(choice["required"]).issubset(value) for choice in rule["oneOf"]) != 1:
            raise InvalidInput()
        properties = rule.get("properties", {})
        for name, item in value.items():
            if "propertyNames" in rule:
                validate(name, rule["propertyNames"])
            if name in properties:
                validate(item, properties[name])
            elif isinstance(rule.get("additionalProperties"), dict):
                validate(item, rule["additionalProperties"])
            else:
                raise InvalidInput()
    elif kind == "string":
        if not isinstance(value, str) or any(ord(c) < 32 for c in value):
            raise InvalidInput()
        if not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", 128):
            raise InvalidInput()
        if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
            raise InvalidInput()
    elif kind == "integer":
        if type(value) is not int or not rule["minimum"] <= value <= rule["maximum"]:
            raise InvalidInput()
    elif kind == "boolean":
        if type(value) is not bool:
            raise InvalidInput()
    elif kind == "array":
        if not isinstance(value, list) or not rule["minItems"] <= len(value) <= rule["maxItems"]:
            raise InvalidInput()
        for item in value:
            validate(item, rule["items"])
        if rule.get("uniqueItems") and len(set(value)) != len(value):
            raise InvalidInput()


def operation(client, name, arguments):
    if name not in TOOLS:
        raise InvalidInput()
    validate(arguments, TOOLS[name][1])
    if name in {"compare_prices", "get_competitor_prices"}:
        scenario = arguments["scenario"]
        try:
            if datetime.fromisoformat(scenario["as_of"].replace("Z", "+00:00")).utcoffset() is None:
                raise ValueError()
            if "usage_per_month" in scenario:
                value = scenario["usage_per_month"]
                if not re.fullmatch(r"\d{1,18}(?:\.\d{1,8})?", value) or len(value.replace(".", "").lstrip("0")) > 18:
                    raise ValueError()
                if not Decimal(value).is_finite():
                    raise ValueError()
        except (ValueError, InvalidOperation):
            raise InvalidInput() from None
        if name == "get_competitor_prices":
            return lambda: client.competitor_prices(**arguments)
        return lambda: client.compare(arguments["snapshot_ids"], scenario)
    if name == "search_products":
        return lambda: client.search(arguments["query"], limit=arguments.get("limit", 20), offset=arguments.get("offset", 0))
    if name == "get_prices":
        return lambda: client.prices(arguments.get("product_id"), limit=arguments.get("limit", 20), offset=arguments.get("offset", 0))
    if name == "get_price_history":
        return lambda: client.history(arguments["product_id"], limit=arguments.get("limit", 20), offset=arguments.get("offset", 0))
    method, argument = {"get_price": (client.price, "snapshot_id"), "get_sources": (client.sources, "snapshot_id"),
                        "get_reviewed_records": (client.records, "domain"), "get_usage": (client.usage, None)}[name]
    return (lambda: method()) if argument is None else (lambda: method(arguments[argument]))


def safe_error(code, message, *, status=None, retry_after=None):
    return {"schema_version": 1, "error": {"code": code, "message": message, "status": status, "retry_after": retry_after}}


async def execute(client, runner, name, arguments):
    try:
        action = operation(client, name, arguments)
        payload = await runner.run(action)
        text = ("Source-backed data. Automated observations are not human verification; recorded review remains qualified per fact.\n"
                + human(payload))
        text_bytes = text.encode("utf-8")
        if len(text_bytes) > MAX_TEXT_BYTES:
            text = text_bytes[:MAX_TEXT_BYTES - 96].decode("utf-8", errors="ignore") + "\nText truncated; full qualifications remain in structuredContent."
        bounded_json({"content": [{"type": "text", "text": text}], "structuredContent": payload}, MAX_TOOL_BYTES)
        return payload, text, False
    except InvalidInput:
        error = safe_error("invalid_input", "Unknown tool or invalid bounded arguments")
    except ClientError as exc:
        error = {"schema_version": 1, "error": exc.as_dict()}
    except Busy:
        error = safe_error("busy", "An earlier REST operation is still running; no new request was issued")
    except DeadlineExceeded:
        error = safe_error("deadline_exceeded", "Response deadline exceeded; the actual REST operation retains its permit until finished")
    except Exception:
        error = safe_error("operation_failed", "Pricing operation failed safely")
    return error, error["error"]["message"], True


def bounded_json(value, maximum):
    output = bytearray()
    for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":")).iterencode(value):
        encoded = chunk.encode("utf-8")
        if len(output) + len(encoded) > maximum:
            raise ValueError("Serialized response exceeds bound")
        output.extend(encoded)
    return bytes(output)
