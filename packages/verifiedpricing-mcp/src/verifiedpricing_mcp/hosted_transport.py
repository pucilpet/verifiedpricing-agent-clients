"""Bounded per-caller HTTP shell; the official SDK owns every MCP message."""

import json
import re

import anyio
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types.version import SUPPORTED_PROTOCOL_VERSIONS

MAX_BODY = 64 * 1024
MAX_RESPONSE = 768 * 1024
PRIVACY = [(b'cache-control', b'private, no-store, max-age=0'),
           (b'referrer-policy', b'no-referrer'), (b'x-robots-tag', b'noindex'),
           (b'x-content-type-options', b'nosniff')]


class AsyncRunner:
    """Await cancellable I/O directly: no detached workers or submission backlog."""

    async def run(self, operation):
        return await operation()


def contains_secret(value, secret):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and secret in item:
            return True
    return False


class HostedMCP:
    def __init__(self, *, create_server, client_factory, authenticate, host, origin,
                 concurrency=4, deadline=20):
        self.create_server = create_server
        self.client_factory = client_factory
        self.authenticate = authenticate
        self.host, self.origin = host, origin
        self.concurrency, self.deadline = concurrency, deadline
        self.active = 0
        self.body_readers = 0
        self.body_readers_limit = max(8, concurrency * 2)
        self.body_deadline = min(5, deadline)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            while True:
                message = await receive()
                if message['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif message['type'] == 'lifespan.shutdown':
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        if scope['type'] != 'http':
            return
        if scope['path'] == '/healthz' and scope['method'] == 'GET':
            await self.respond(send, 200, b'{"ok":true}')
            return
        if scope['path'] != '/mcp':
            await self.respond(send, 404)
            return
        headers = {}
        raw_headers = scope.get('headers', [])
        if len(raw_headers) > 64 or sum(len(k) + len(v) for k, v in raw_headers) > 16384:
            await self.respond(send, 431)
            return
        for name, value in raw_headers:
            name = name.lower()
            if name in headers:
                await self.respond(send, 400)
                return
            headers[name] = value.decode('latin-1')
        if headers.get(b'host') != self.host:
            await self.respond(send, 421)
            return
        if headers.get(b'origin', self.origin) != self.origin:
            await self.respond(send, 403)
            return
        if scope.get('query_string'):
            await self.respond(send, 400)
            return
        if scope['method'] != 'POST':
            await self.respond(send, 405, extra=[(b'allow', b'POST')])
            return
        if (b'mcp-session-id' in headers or b'last-event-id' in headers
                or headers.get(b'mcp-protocol-version', '2025-11-25') not in SUPPORTED_PROTOCOL_VERSIONS):
            await self.respond(send, 400)
            return
        authorization = headers.get(b'authorization', '')
        match = re.fullmatch(r'Bearer ([\x21-\x7e]{1,4096})', authorization, re.IGNORECASE)
        if not match:
            await self.respond(send, 401, extra=[(b'www-authenticate', b'Bearer')])
            return
        if headers.get(b'content-type', '').split(';')[0].lower() != 'application/json':
            await self.respond(send, 415)
            return
        if headers.get(b'content-encoding', 'identity') != 'identity':
            await self.respond(send, 415)
            return
        declared = headers.get(b'content-length')
        if declared is not None and (len(declared) > 12 or not declared.isascii() or not declared.isdecimal()):
            await self.respond(send, 400)
            return
        if declared is not None and int(declared) > MAX_BODY:
            await self.respond(send, 413)
            return
        # Uvicorn bounds initial HTTP readers. Only partial bodies reserve this
        # additional pool; complete first frames can pass even when it is full.
        started = anyio.current_time()
        partial_permit = False
        try:
            with anyio.fail_after(min(self.body_deadline, self.deadline)):
                body = bytearray()
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    chunk = message.get('body', b'')
                    if len(body) + len(chunk) > MAX_BODY:
                        await self.respond(send, 413, extra=[(b'connection', b'close')])
                        return
                    body.extend(chunk)
                    if not message.get('more_body', False):
                        break
                    if not partial_permit:
                        if self.body_readers >= self.body_readers_limit:
                            await self.respond(send, 503, extra=[(b'retry-after', b'2'), (b'connection', b'close')])
                            return
                        self.body_readers += 1
                        partial_permit = True
        except TimeoutError:
            await self.respond(send, 408, extra=[(b'connection', b'close')])
            return
        finally:
            if partial_permit:
                self.body_readers -= 1
        # Privacy inspection is not JSON-RPC dispatch; the SDK still owns every
        # valid protocol message and its validation/handshake behavior.
        try:
            decoded = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            await self.respond(send, 400)
            return
        if contains_secret(decoded, match[1]):
            await self.respond(send, 400)
            return
        if self.active >= self.concurrency:
            await self.respond(send, 503, extra=[(b'retry-after', b'2')])
            return
        remaining = self.deadline - (anyio.current_time() - started)
        if remaining <= 0:
            await self.respond(send, 408, extra=[(b'connection', b'close')])
            return
        self.active += 1
        try:
            with anyio.fail_after(remaining):
                await self.serve(scope, receive, send, match[1], bytes(body))
        except TimeoutError:
            await self.respond(send, 504)
        except Exception:
            # SDK and upstream exceptions can contain credentials or source text.
            await self.respond(send, 502)
        finally:
            self.active -= 1

    async def serve(self, scope, receive, send, secret, body):
        disconnected = anyio.Event()
        cached = True
        response = []
        size = 0

        async def replay():
            nonlocal cached
            if cached:
                cached = False
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            await disconnected.wait()
            return {'type': 'http.disconnect'}

        async def collect(message):
            nonlocal size
            size += len(message.get('body', b''))
            if size > MAX_RESPONSE:
                raise ValueError('Response bound')
            response.append(message)

        async with anyio.create_task_group() as group:
            async def monitor():
                while True:
                    if (await receive())['type'] == 'http.disconnect':
                        disconnected.set()
                        group.cancel_scope.cancel()
                        return
            group.start_soon(monitor)
            async with self.client_factory(secret) as client:
                status = await self.authenticate(client)
                if status != 200:
                    await self.respond(send, status, extra=[(b'www-authenticate', b'Bearer')] if status == 401 else [])
                    group.cancel_scope.cancel()
                    return
                server = self.create_server(client, AsyncRunner())
                manager = StreamableHTTPSessionManager(
                    server, json_response=True, stateless=True, max_request_body_size=MAX_BODY,
                    security_settings=TransportSecuritySettings(
                        allowed_hosts=[self.host], allowed_origins=[self.origin]))
                async with manager.run():
                    await manager.handle_request(scope, replay, collect)
            group.cancel_scope.cancel()
        if disconnected.is_set():
            return
        raw = b''.join(item.get('body', b'') for item in response)
        if raw:
            payload = json.loads(raw)
            if contains_secret(payload, secret):
                await self.respond(send, 502)
                return
            if isinstance(payload, dict) and isinstance(payload.get('error'), dict):
                # Validation diagnostics may contain shortened input_value excerpts;
                # removing data/message details also removes credential fragments.
                code = payload['error'].get('code')
                payload['error'] = {'code': code if type(code) is int else -32603,
                                    'message': 'Invalid MCP request'}
                if type(payload.get('id')) not in (str, int, type(None)):
                    payload['id'] = None
                raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()
        start = next((item for item in response if item['type'] == 'http.response.start'), None)
        if start is None:
            await self.respond(send, 502)
            return
        start['headers'] = [(k, v) for k, v in start.get('headers', [])
                            if k.lower() not in {k for k, _ in PRIVACY} | {b'content-length'}]
        start['headers'] += PRIVACY + [(b'content-length', str(len(raw)).encode())]
        await send(start)
        await send({'type': 'http.response.body', 'body': raw})

    @staticmethod
    async def respond(send, status, body=b'', extra=()):
        await send({'type': 'http.response.start', 'status': status,
                    'headers': PRIVACY + [(b'content-type', b'application/json'),
                                          (b'content-length', str(len(body)).encode())] + list(extra)})
        await send({'type': 'http.response.body', 'body': body})
