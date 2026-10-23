"""No retries, redirects, cookies or implicit credential forwarding."""

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
import math
import re
import urllib.error
import urllib.parse
import urllib.request

MAX_BODY_BYTES = 512 * 1024
_SNAPSHOT = re.compile(r"po_[0-9a-f]{64}\Z")
_DOMAIN = re.compile(r"(?=.{1,253}\Z)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")
_COVERAGE_REQUEST = re.compile(r"cr_[0-9a-f]{32}\Z")
COVERAGE_CATEGORIES = ("seo", "email marketing", "crm", "analytics", "project management",
                       "customer support", "social media", "hosting")


class ClientError(Exception):
    def __init__(self, code, message, *, status=None, retry_after=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.status, self.retry_after = status, retry_after

    def as_dict(self):
        return {"code": self.code, "message": self.message,
                "status": self.status, "retry_after": self.retry_after}


def validate_base_url(value, allow_localhost=False):
    try:
        parts = urllib.parse.urlsplit(value)
        port = parts.port
    except ValueError:
        raise ClientError("configuration", "Invalid API base URL") from None
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or parts.path not in ("", "/") or any(ord(c) <= 32 for c in value)
            or parts.scheme not in {"https", "http"}
            or (parts.scheme == "http" and not (allow_localhost and local))
            or port == 0):
        raise ClientError("configuration", "Use an HTTPS origin; HTTP requires explicit localhost development mode")
    return value.rstrip("/")


def validate_key(value):
    if value is not None and (not isinstance(value, str) or not value or len(value) > 4096
                              or any(ord(c) <= 32 or ord(c) >= 127 for c in value)):
        raise ClientError("configuration", "Invalid API credential format")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _identifier(value, snapshot=False):
    if (not isinstance(value, str) or not 1 <= len(value) <= 128
            or any(ord(c) < 32 for c in value)
            or (snapshot and not _SNAPSHOT.fullmatch(value))):
        raise ClientError("input", "Invalid snapshot or product identifier")
    return urllib.parse.quote(value, safe="")


def _page(limit, offset):
    if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 50 or not 0 <= offset <= 10000:
        raise ClientError("input", "Page limit must be 1..50 and offset 0..10000")
    return {"limit": limit, "offset": offset}


def _scenario(value):
    fields = {"as_of", "currency", "market", "months", "seats", "usage_per_month", "usage_unit", "allow_stale"}
    if (not isinstance(value, dict) or set(value) - fields
            or not {"as_of", "currency", "market"}.issubset(value)):
        raise ClientError("input", "Provide an explicit bounded comparison scenario")
    try:
        if (not isinstance(value["as_of"], str) or len(value["as_of"]) > 64
                or datetime.fromisoformat(value["as_of"].replace("Z", "+00:00")).utcoffset() is None
                or not isinstance(value["currency"], str) or not re.fullmatch(r"[A-Z]{3}", value["currency"])
                or not isinstance(value["market"], str) or not 2 <= len(value["market"]) <= 64
                or any(ord(c) < 32 for c in value["market"])):
            raise ValueError()
        for name, default, maximum in (("months", 12, 120), ("seats", 1, 1000000)):
            number = value.get(name, default)
            if type(number) is not int or not 1 <= number <= maximum:
                raise ValueError()
        if "allow_stale" in value and type(value["allow_stale"]) is not bool:
            raise ValueError()
        if "usage_unit" in value and (not isinstance(value["usage_unit"], str)
                or not 1 <= len(value["usage_unit"]) <= 64 or any(ord(c) < 32 for c in value["usage_unit"])):
            raise ValueError()
        if "usage_per_month" in value:
            usage = value["usage_per_month"]
            if type(usage) not in (str, int) or len(str(usage)) > 64:
                raise ValueError()
            decimal = Decimal(usage)
            if not decimal.is_finite() or decimal < 0:
                raise ValueError()
            _, digits, exponent = decimal.as_tuple()
            digits = list(digits)
            while len(digits) > 1 and digits[-1] == 0:
                digits.pop()
                exponent += 1
            fractional = max(-exponent, 0)
            if fractional > 8 or max(len(digits) + exponent, 0) + fractional > 18:
                raise ValueError()
    except (ValueError, InvalidOperation, OverflowError, TypeError):
        raise ClientError("input", "Invalid bounded comparison scenario") from None


class Client:
    def __init__(self, base_url="https://verifiedpricing.com", api_key=None, *,
                 allow_localhost=False, timeout=15):
        self.base_url = validate_base_url(base_url, allow_localhost)
        self._key = validate_key(api_key)
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ClientError("configuration", "Timeout must be greater than zero and at most 60 seconds")
        self.timeout = timeout
        # Ignore environment proxies, which could otherwise receive a development bearer key.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def request(self, method, path, *, query=None, body=None):
        if method not in {"GET", "POST"} or not path.startswith("/api/v1/") or "?" in path or "#" in path:
            raise ClientError("input", "Unsupported API request")
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json", "User-Agent": "verifiedpricing-client/0.1.3"}
        if self._key:
            headers["Authorization"] = "Bearer " + self._key
        try:
            data = None if body is None else json.dumps(body, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError):
            raise ClientError("input", "Request must contain JSON-compatible exact values") from None
        if data is not None:
            if len(data) > 16384:
                raise ClientError("input", "Request exceeds the client size limit")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            response = self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            response = exc
        except (OSError, urllib.error.URLError, HTTPException, ValueError):
            raise ClientError("transport", "API connection failed or timed out") from None
        with response:
            status = response.status
            try:
                raw = response.read(MAX_BODY_BYTES + 1)
            except (OSError, HTTPException, ValueError):
                raise ClientError("transport", "API response failed or timed out") from None
            retry = response.headers.get("Retry-After")
            # Retry-After may be seconds or an HTTP date; it is informational, never retried.
            if retry is not None and (len(retry) > 80 or any(ord(c) < 32 for c in retry)):
                retry = None
            if self._key and retry and self._key in retry:
                retry = None
            if len(raw) > MAX_BODY_BYTES:
                raise ClientError("response_too_large", "API response exceeds the client size limit", status=status)
            try:
                def invalid_constant(value):
                    raise ValueError()
                payload = json.loads(raw, parse_constant=invalid_constant)
            except (ValueError, UnicodeError, RecursionError):
                payload = None
            if status != 200:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                code = detail.get("code") if isinstance(detail, dict) else None
                if (not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code)
                        or (self._key and self._key in code)):
                    code = "rate_limited" if status == 429 else "http_error"
                message = ("API redirect refused" if 300 <= status < 400 else
                           "API authentication failed" if status in (401, 403) else
                           "API request limited" if status == 429 else "API request failed")
                # Server details can echo submitted credentials; never print raw error bodies.
                raise ClientError(code, message, status=status, retry_after=retry)
            if (not isinstance(payload, dict) or type(payload.get("schema_version")) is not int
                    or payload["schema_version"] != 1 or not isinstance(payload.get("data"), dict)
                    or not isinstance(payload.get("usage"), dict)):
                raise ClientError("invalid_response", "Unsupported API response envelope", status=status)
            if self._key:
                # Inspect decoded strings as well: JSON escapes must not hide an echoed key.
                pending = [payload]
                while pending:
                    value = pending.pop()
                    if isinstance(value, dict):
                        pending.extend(value.keys())
                        pending.extend(value.values())
                    elif isinstance(value, list):
                        pending.extend(value)
                    elif isinstance(value, str) and self._key in value:
                        raise ClientError("invalid_response", "API response contains credential material", status=status)
            return payload

    def prices(self, product_id=None, *, limit=20, offset=0):
        query = _page(limit, offset)
        if product_id is not None:
            _identifier(product_id)
            query["product_id"] = product_id
        return self.request("GET", "/api/v1/prices", query=query)

    def price(self, snapshot_id):
        return self.request("GET", "/api/v1/prices/" + _identifier(snapshot_id, True))

    def compare(self, snapshot_ids, scenario):
        if not 2 <= len(snapshot_ids) <= 3 or len(set(snapshot_ids)) != len(snapshot_ids):
            raise ClientError("input", "Provide two or three distinct snapshot IDs")
        for value in snapshot_ids:
            _identifier(value, True)
        return self.request("POST", "/api/v1/comparisons", body={"snapshot_ids": list(snapshot_ids), "scenario": scenario})

    def usage(self):
        return self.request("GET", "/api/v1/usage")

    def search(self, query, *, limit=20, offset=0):
        if not isinstance(query, str) or not 1 <= len(query) <= 100 or any(ord(c) < 32 for c in query):
            raise ClientError("input", "Search requires 1..100 characters")
        return self.request("GET", "/api/v1/products", query={**_page(limit, offset), "q": query})

    def history(self, product_id, *, limit=20, offset=0):
        return self.request("GET", "/api/v1/products/" + _identifier(product_id) + "/history", query=_page(limit, offset))

    def sources(self, snapshot_id):
        return self.request("GET", "/api/v1/prices/" + _identifier(snapshot_id, True) + "/sources")

    def records(self, domain):
        if not isinstance(domain, str):
            raise ClientError("input", "Provide a domain name without a URL or IP address")
        domain = domain.lower().rstrip(".")
        if not _DOMAIN.fullmatch(domain):
            raise ClientError("input", "Provide a domain name without a URL or IP address")
        return self.request("GET", "/api/v1/records/" + domain)

    def request_price_coverage(self, *, consent=False, product_id=None, domain=None,
                               category=None, product_name=None):
        if consent is not True:
            raise ClientError("input", "Explicit consent is required to queue pricing research")
        if (product_id is None) == (domain is None):
            raise ClientError("input", "Provide exactly one product ID or canonical domain")
        body = {"consent": True}
        if product_id is not None:
            if not isinstance(product_id, str) or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}", product_id):
                raise ClientError("input", "Invalid product identifier")
            body["product_id"] = product_id
        else:
            if not isinstance(domain, str) or not _DOMAIN.fullmatch(domain):
                raise ClientError("input", "Provide a canonical lowercase domain without a URL or IP address")
            body["domain"] = domain
        if category is not None:
            if not isinstance(category, str) or category not in COVERAGE_CATEGORIES:
                raise ClientError("input", "Unsupported pricing research category")
            body["category"] = category
        if product_name is not None:
            if (not isinstance(product_name, str) or not 1 <= len(product_name) <= 120
                    or product_name != product_name.strip() or any(ord(c) < 32 or ord(c) == 127
                                                     or c in "\u2028\u2029" for c in product_name)):
                raise ClientError("input", "Provide a bounded product name")
            body["product_name"] = product_name
        return self.request("POST", "/api/v1/coverage-requests", body=body)

    def price_coverage_request(self, request_id):
        if not isinstance(request_id, str) or not _COVERAGE_REQUEST.fullmatch(request_id):
            raise ClientError("input", "Invalid pricing coverage request identifier")
        return self.request("GET", "/api/v1/coverage-requests/" + request_id)

    def competitor_prices(self, *, scenario, product_id=None, domain=None, limit=3, selections=None, competitor_product_id=None):
        if (product_id is None) == (domain is None):
            raise ClientError("input", "Provide exactly one seed product ID or canonical domain")
        if type(limit) is not int or limit not in (2, 3):
            raise ClientError("input", "Total product limit including the seed must be two or three")
        _scenario(scenario)
        body = {"scenario": scenario, "limit": limit}
        if product_id is not None:
            if not isinstance(product_id, str) or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}", product_id):
                raise ClientError("input", "Invalid seed product identifier")
            body["product_id"] = product_id
        else:
            if not isinstance(domain, str) or not _DOMAIN.fullmatch(domain):
                raise ClientError("input", "Provide a canonical lowercase domain without a URL or IP address")
            body["domain"] = domain
        if competitor_product_id is not None:
            if not isinstance(competitor_product_id, str) or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}", competitor_product_id):
                raise ClientError("input", "Invalid competitor product identifier")
            body["competitor_product_id"] = competitor_product_id
        if selections is not None:
            if not isinstance(selections, dict) or len(selections) > 3:
                raise ClientError("input", "Provide at most three explicit snapshot selections")
            for selected_product, snapshot in selections.items():
                if not isinstance(selected_product, str) or not re.fullmatch(r"[A-Za-z0-9:_.-]{1,128}", selected_product):
                    raise ClientError("input", "Invalid selected product identifier")
                _identifier(snapshot, True)
            body["selections"] = selections
        return self.request("POST", "/api/v1/competitor-prices", body=body)
