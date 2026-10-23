"""Hosted adapter over the existing account-scoped REST surface."""

from contextlib import asynccontextmanager
import json
import logging.config

import httpx2

from .hosted_transport import HostedMCP, contains_secret
from verifiedpricing_client import Client, ClientError
from verifiedpricing_client.client import MAX_BODY_BYTES, validate_key
from . import __version__
from .server import create_server

API_ORIGIN = 'http://engine:8000'


class AsyncClient(Client):
    def __init__(self, key, http):
        self._key = validate_key(key)
        self.http = http

    async def request(self, method, path, *, query=None, body=None):
        if method not in {'GET', 'POST'} or not path.startswith('/api/v1/') or '?' in path or '#' in path:
            raise ClientError('input', 'Unsupported API request')
        try:
            data = None if body is None else json.dumps(body, allow_nan=False, separators=(',', ':')).encode()
            if data is not None and len(data) > 16384:
                raise ClientError('input', 'Request exceeds the client size limit')
            async with self.http.stream(method, API_ORIGIN + path, params=query, content=data,
                    headers={'Authorization': 'Bearer ' + self._key, 'Accept': 'application/json',
                             'Content-Type': 'application/json', 'User-Agent': 'verifiedpricing-hosted-mcp/' + __version__}) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > MAX_BODY_BYTES:
                        raise ClientError('response_too_large', 'API response exceeds the client size limit')
                    raw.extend(chunk)
                if response.status_code != 200:
                    status = response.status_code
                    code = 'rate_limited' if status == 429 else 'http_error'
                    retry = response.headers.get('Retry-After')
                    if retry is not None and (len(retry) > 80 or any(ord(c) < 32 for c in retry)
                                              or self._key in retry):
                        retry = None
                    raise ClientError(code, 'Pricing API request failed', status=status, retry_after=retry)
                def invalid_constant(value):
                    raise ValueError()
                payload = json.loads(raw, parse_constant=invalid_constant)
                if (not isinstance(payload, dict) or type(payload.get('schema_version')) is not int
                        or payload['schema_version'] != 1 or not isinstance(payload.get('data'), dict)
                        or not isinstance(payload.get('usage'), dict) or contains_secret(payload, self._key)):
                    raise ValueError()
                return payload
        except ClientError:
            raise
        except (ValueError, UnicodeError, RecursionError):
            raise ClientError('invalid_response', 'Unsupported API response envelope') from None
        except httpx2.HTTPError:
            raise ClientError('transport', 'API connection failed or timed out') from None


@asynccontextmanager
async def client_factory(key):
    async with httpx2.AsyncClient(trust_env=False, follow_redirects=False, timeout=12,
                                limits=httpx2.Limits(max_connections=1, max_keepalive_connections=0)) as http:
        yield AsyncClient(key, http)


async def authenticate(client):
    try:
        await client.usage()
        return 200
    except ClientError as error:
        return error.status if error.status in {401, 403, 429, 503} else 502


app = HostedMCP(create_server=create_server, client_factory=client_factory,
                authenticate=authenticate, host='verifiedpricing.com', origin='https://verifiedpricing.com')


def suppress_private_logs():
    # Protocol libraries may otherwise log malformed frames, origins or tool arguments.
    logging.config.dictConfig({'version': 1, 'disable_existing_loggers': True,
                              'handlers': {'null': {'class': 'logging.NullHandler'}},
                              'root': {'handlers': ['null'], 'level': 'CRITICAL'}})
    for name in ('mcp', 'mcp_types', 'httpx2'):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False


def main():
    import uvicorn
    suppress_private_logs()
    uvicorn.run(app, host='0.0.0.0', port=8080, workers=1, access_log=False, log_config=None,
                limit_concurrency=16, timeout_keep_alive=5, timeout_graceful_shutdown=25)


if __name__ == '__main__':
    main()
