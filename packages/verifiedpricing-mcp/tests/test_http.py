"""Real SDK transport over ASGI, with an account-budget REST fixture."""

import asyncio
from contextlib import asynccontextmanager
import json
import socket
import os
import subprocess
import sys
import unittest

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from verifiedpricing_mcp.hosted_transport import HostedMCP, MAX_BODY
from verifiedpricing_mcp.http import AsyncClient, authenticate
from verifiedpricing_mcp.server import create_server

KEY = 'fixture-vp-personal-key'
SECOND_KEY = 'fixture-vp-second-key'
ORIGIN = 'https://verifiedpricing.com'
HEADERS = {'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json',
           'Accept': 'application/json, text/event-stream'}
META = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientCapabilities': {}}


def frame(method='tools/list', arguments=None):
    params = {'_meta': META}
    if method == 'tools/call':
        params.update({'name': 'get_prices', 'arguments': arguments or {}})
    return {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.used = {KEY: 0, SECOND_KEY: 0}
        self.revoked = set()
        self.calls = []
        self.closed = 0
        self.block = None
        self.errors = {}
        self.payload = None
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

        async def upstream(request):
            key = request.headers.get('authorization', '').removeprefix('Bearer ')
            self.calls.append((request.method, str(request.url), key))
            if key not in self.used or key in self.revoked:
                return httpx2.Response(401, json={'detail': 'invalid'})
            if request.url.path in self.errors:
                return httpx2.Response(self.errors[request.url.path], json={'detail': key})
            if self.payload is not None:
                return httpx2.Response(200, json=self.payload)
            if request.url.path != '/api/v1/usage':
                if self.block:
                    self.started.set()
                    try:
                        await self.block.wait()
                    except asyncio.CancelledError:
                        self.cancelled.set()
                        raise
                self.used[key] += 1
            return httpx2.Response(200, json={'schema_version': 1,
                    'data': {'observations': [], 'next_offset': None},
                    'usage': {'month': {'used': self.used[key], 'limit': 10000}}})

        @asynccontextmanager
        async def factory(key):
            try:
                async with httpx2.AsyncClient(transport=httpx2.MockTransport(upstream), trust_env=False,
                                             follow_redirects=False) as http:
                    yield AsyncClient(key, http)
            finally:
                self.closed += 1
        self.app = HostedMCP(create_server=create_server, client_factory=factory, authenticate=authenticate,
                             host='verifiedpricing.com', origin=ORIGIN)
        self.http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=self.app),
                                      base_url=ORIGIN, headers=HEADERS)

    async def asyncTearDown(self):
        await self.http.aclose()
        self.assertEqual(self.app.active, 0)

    async def test_genuine_sdk_coverage_tools_forward_exact_rest_identity(self):
        request_id = 'cr_' + 'a' * 32
        self.payload = {'schema_version': 1, 'data': {'id': request_id, 'status': 'queued',
                        'domain': 'product.example', 'revision': 1}, 'usage': {'day': {'used': 1}}}
        async with streamable_http_client(ORIGIN + '/mcp', http_client=self.http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                listed = await session.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                self.assertFalse(tools['request_price_coverage'].annotations.read_only_hint)
                self.assertTrue(tools['request_price_coverage'].annotations.idempotent_hint)
                self.assertTrue(tools['get_price_coverage_request'].annotations.read_only_hint)
                requested = await session.call_tool('request_price_coverage',
                    {'domain': 'product.example', 'category': 'seo', 'consent': True})
                self.assertFalse(requested.is_error)
                self.assertEqual(requested.structured_content, self.payload)
                status = await session.call_tool('get_price_coverage_request', {'request_id': request_id})
                self.assertFalse(status.is_error)
                self.assertEqual(status.structured_content, self.payload)
        operations = [(method, url, key) for method, url, key in self.calls if not url.endswith('/usage')]
        self.assertEqual(operations, [('POST', 'http://engine:8000/api/v1/coverage-requests', KEY),
                                     ('GET', 'http://engine:8000/api/v1/coverage-requests/' + request_id, KEY)])

    async def test_genuine_sdk_handshake_eleven_tools_and_shared_allowance(self):
        async with streamable_http_client(ORIGIN + '/mcp', http_client=self.http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                initialized = await session.initialize()
                self.assertEqual(initialized.server_info.name, 'verifiedpricing')
                listed = await session.list_tools()
                self.assertEqual(len(listed.tools), 11)
                self.assertEqual(self.used[KEY], 0)
                called = await session.call_tool('get_prices', {})
                self.assertFalse(called.is_error)
                self.assertEqual(called.structured_content['usage']['month']['used'], 1)
                # REST and another hosted call use the same account ledger, never a transport allowance.
                self.used[KEY] += 1
                called = await session.call_tool('get_prices', {})
                self.assertEqual(called.structured_content['usage']['month']['used'], 3)
        self.assertTrue(all(key == KEY for _, _, key in self.calls))
        self.assertTrue(all(url.startswith('http://engine:8000/api/v1/') for _, url, _ in self.calls))
        self.assertGreaterEqual(self.closed, 4)

    async def test_modern_sdk_request_and_no_session_or_sse(self):
        result = await self.http.post('/mcp', json=frame())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.json()['result']['tools']), 11)
        self.assertNotIn('mcp-session-id', result.headers)
        self.assertIn('application/json', result.headers['content-type'])
        self.assertIn('no-store', result.headers['cache-control'])
        self.assertEqual(result.headers['referrer-policy'], 'no-referrer')
        self.assertEqual(self.used[KEY], 0)

    async def test_personal_keys_do_not_cross_requests(self):
        one = await self.http.post('/mcp', json=frame('tools/call'))
        two = await self.http.post('/mcp', json=frame('tools/call'),
                                   headers={'Authorization': 'Bearer ' + SECOND_KEY})
        self.assertEqual((one.status_code, two.status_code), (200, 200))
        self.assertEqual(self.used, {KEY: 1, SECOND_KEY: 1})

    async def test_missing_invalid_and_revoked_keys_authenticate_before_list(self):
        self.revoked.add(KEY)
        for key in ('', 'Bearer invalid', 'Bearer ' + KEY):
            result = await self.http.post('/mcp', json=frame(), headers={'Authorization': key})
            self.assertEqual(result.status_code, 401)
            self.assertNotIn('tools', result.text)
        self.assertEqual(self.used[KEY], 0)

    async def test_host_origin_query_and_methods_rejected_without_upstream(self):
        for headers, path, method, expected in [
                ({'Host': 'quotedwrong.com'}, '/mcp', 'POST', 421),
                ({'Origin': 'https://hostile.example'}, '/mcp', 'POST', 403),
                ({}, f'/mcp?apiKey={KEY}', 'POST', 400),
                ({}, '/mcp', 'GET', 405), ({}, '/mcp', 'DELETE', 405),
                ({'Mcp-Session-Id': 'unwanted'}, '/mcp', 'POST', 400),
                ({'MCP-Protocol-Version': 'unknown'}, '/mcp', 'POST', 400)]:
            response = await self.http.request(method, path, headers=headers, json=frame())
            self.assertEqual(response.status_code, expected)
            self.assertNotIn(KEY, response.text)
        self.assertEqual(self.calls, [])

    async def test_oversized_malformed_and_tool_credentials(self):
        oversized = await self.http.post('/mcp', content=b' ' * (MAX_BODY + 1))
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(self.calls, [])
        malformed = await self.http.post('/mcp', content=b'{')
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(self.used[KEY], 0)
        tool = await self.http.post('/mcp', json=frame('tools/call', {'api_key': 'unwanted'}))
        self.assertTrue(tool.json()['result']['isError'])
        self.assertEqual(self.used[KEY], 0)

    async def test_deadline_cancels_actual_async_io_and_closes_client(self):
        self.block = asyncio.Event()
        self.app.deadline = 0.05
        result = await self.http.post('/mcp', json=frame('tools/call'))
        self.assertEqual(result.status_code, 504)
        self.assertTrue(self.cancelled.is_set())
        self.assertEqual(self.closed, 1)
        self.assertEqual(self.used[KEY], 0)

    async def test_immediate_concurrency_admission_no_backlog(self):
        self.block = asyncio.Event()
        self.app.concurrency = 1
        first = asyncio.create_task(self.http.post('/mcp', json=frame('tools/call')))
        await asyncio.wait_for(self.started.wait(), 1)
        second = await self.http.post('/mcp', json=frame('tools/call'))
        self.assertEqual(second.status_code, 503)
        self.assertEqual(len(self.calls), 2)
        self.block.set()
        self.assertEqual((await first).status_code, 200)

    async def test_disconnect_cancels_actual_io_and_owned_scope(self):
        self.block = asyncio.Event()
        body = json.dumps(frame('tools/call')).encode()
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type': 'http.request', 'body': body}
            await self.started.wait()
            return {'type': 'http.disconnect'}
        sent = []
        async def send(message):
            sent.append(message)
        scope = {'type': 'http', 'method': 'POST', 'path': '/mcp', 'query_string': b'',
                 'headers': [(k.lower().encode(), v.encode()) for k, v in
                             {**HEADERS, 'Host': 'verifiedpricing.com'}.items()]}
        await asyncio.wait_for(self.app(scope, receive, send), 1)
        self.assertTrue(self.cancelled.is_set())
        self.assertEqual(self.closed, 1)
        self.assertEqual(sent, [])
        self.assertEqual(self.used[KEY], 0)

    async def test_reject_duplicate_auth_headers(self):
        result = await self.http.post('/mcp', json=frame(),
                     headers=[('Authorization', 'Bearer ' + KEY), ('Authorization', 'Bearer ' + SECOND_KEY)])
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.calls, [])

    async def test_real_loopback_http_sdk_client(self):
        import uvicorn
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.listen(8)
        server = uvicorn.Server(uvicorn.Config(self.app, log_config=None, access_log=False,
                                              log_level='critical', lifespan='on'))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.005)
            self.assertTrue(server.started)
            async with httpx2.AsyncClient(headers={**HEADERS, 'Host': 'verifiedpricing.com'},
                                           trust_env=False) as http:
                async with streamable_http_client(f'http://127.0.0.1:{port}/mcp', http_client=http) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        self.assertEqual(len((await session.list_tools()).tools), 11)
                        self.assertFalse((await session.call_tool('get_prices', {})).is_error)
            self.assertEqual(self.used[KEY], 1)
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 2)
            listener.close()

    async def test_api_scope_and_exhausted_quota_remain_authoritative(self):
        for status in (403, 429):
            self.errors['/api/v1/prices'] = status
            result = await self.http.post('/mcp', json=frame('tools/call'))
            payload = result.json()['result']
            self.assertTrue(payload['isError'])
            self.assertEqual(payload['structuredContent']['error']['status'], status)
            self.assertNotIn(KEY, result.text)
        self.assertEqual(self.used[KEY], 0)

    async def test_escaped_credential_echo_and_bad_envelope_never_return(self):
        self.payload = {'schema_version': 1, 'data': {'secret': KEY}, 'usage': {}}
        response = await self.http.post('/mcp', json=frame())
        self.assertEqual(response.status_code, 502)
        self.assertNotIn(KEY, response.text)
        self.payload = {'schema_version': 2, 'data': {}, 'usage': {}}
        self.assertEqual((await self.http.post('/mcp', json=frame())).status_code, 502)

    async def test_sdk_accept_and_protocol_validation(self):
        response = await self.http.post('/mcp', json=frame(), headers={'Accept': 'text/plain'})
        self.assertEqual(response.status_code, 406)
        response = await self.http.post('/mcp', content=b'[]')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.used[KEY], 0)

    async def test_key_in_request_identifier_cannot_echo(self):
        request = frame()
        request['id'] = KEY
        response = await self.http.post('/mcp', json=request)
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(KEY, response.text)

    async def test_production_bootstrap_suppresses_private_library_logs(self):
        script = """
import logging
from verifiedpricing_mcp.http import suppress_private_logs
logging.getLogger('mcp').addHandler(logging.StreamHandler())
suppress_private_logs()
for name in ('mcp', 'mcp.future', 'mcp_types', 'httpx2', 'uvicorn.error', ''):
    logging.getLogger(name).critical('fixture-vp-personal-key')
"""
        result = await asyncio.to_thread(subprocess.run, [sys.executable, '-c', script],
                                         capture_output=True, text=True, timeout=3, env=os.environ.copy())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')

    async def test_decoded_key_in_tool_or_invalid_id_never_reaches_upstream_or_diagnostics(self):
        cases = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
             'params': {'_meta': META, 'name': 'search_products', 'arguments': {'query': KEY}}},
            {'jsonrpc': '2.0', 'id': {'secret': KEY}, 'method': 'tools/list'},
        ]
        for request in cases:
            raw = json.dumps(request).replace(KEY, ''.join('\\u%04x' % ord(c) for c in KEY))
            response = await self.http.post('/mcp', content=raw)
            self.assertEqual(response.status_code, 400)
            for fragment in (KEY, KEY[:12], KEY[-12:]):
                self.assertNotIn(fragment, response.text)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.closed, 0)

    async def test_sdk_validation_errors_drop_untrusted_diagnostic_excerpts(self):
        request = {'jsonrpc': '2.0', 'id': 77, 'method': 'tools/list',
                   'params': {'cursor': {'private': 'private-diagnostic-sentinel'}}}
        response = await self.http.post('/mcp', json=request)
        payload = response.json()
        self.assertEqual(payload['id'], 77)
        self.assertIsInstance(payload['error']['code'], int)
        self.assertEqual(payload['error']['message'], 'Invalid MCP request')
        self.assertNotIn('data', payload['error'])
        self.assertNotIn('private-diagnostic-sentinel', response.text)

    async def test_partial_fake_bodies_do_not_hold_service_slots_or_block_complete_client(self):
        self.app.body_deadline = 0.2
        tasks = []
        receivers_cancelled = []
        sent_lists = []
        for _ in range(self.app.concurrency):
            first = [True]
            cancelled = asyncio.Event()
            sent = []
            async def receive(first=first, cancelled=cancelled):
                if first[0]:
                    first[0] = False
                    return {'type': 'http.request', 'body': b'{', 'more_body': True}
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            async def send(message, sent=sent):
                sent.append(message)
            scope = {'type': 'http', 'method': 'POST', 'path': '/mcp', 'query_string': b'',
                     'headers': [(b'host', b'verifiedpricing.com'), (b'authorization', b'Bearer x'),
                                 (b'content-type', b'application/json'), (b'content-length', b'65536')]}
            tasks.append(asyncio.create_task(self.app(scope, receive, send)))
            receivers_cancelled.append(cancelled)
            sent_lists.append(sent)
        try:
            for _ in range(100):
                if self.app.body_readers == self.app.concurrency:
                    break
                await asyncio.sleep(0.001)
            self.assertEqual(self.app.body_readers, self.app.concurrency)
            self.assertEqual(self.app.active, 0)
            self.assertEqual(self.calls, [])
            result = await self.http.post('/mcp', json=frame('tools/call'))
            self.assertEqual(result.status_code, 200)
            self.assertFalse(result.json()['result']['isError'])
            await asyncio.wait_for(asyncio.gather(*tasks), 1)
            self.assertTrue(all(item.is_set() for item in receivers_cancelled))
            self.assertTrue(all(sent[0]['status'] == 408 for sent in sent_lists))
            self.assertEqual(self.app.body_readers, 0)
            self.assertEqual(self.closed, 1)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_body_reader_pool_is_bounded_and_cancellation_releases_it(self):
        self.app.body_readers_limit = 1
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type': 'http.request', 'body': b'{', 'more_body': True}
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelled.set()
                raise
        async def send(message):
            pass
        scope = {'type': 'http', 'method': 'POST', 'path': '/mcp', 'query_string': b'',
                 'headers': [(b'host', b'verifiedpricing.com'), (b'authorization', b'Bearer x'),
                             (b'content-type', b'application/json')]}
        task = asyncio.create_task(self.app(scope, receive, send))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            result = await self.http.post('/mcp', json=frame())
            self.assertEqual(result.status_code, 503)
            self.assertEqual(self.app.body_readers, 1)
            self.assertEqual(self.app.active, 0)
            self.assertEqual(self.calls, [])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.app.body_readers, 0)
        result = await self.http.post('/mcp', json=frame())
        self.assertEqual(result.status_code, 200)

    async def test_partial_body_disconnect_releases_reader_without_client(self):
        messages = iter([{'type': 'http.request', 'body': b'{', 'more_body': True},
                         {'type': 'http.disconnect'}])
        async def receive():
            return next(messages)
        sent = []
        async def send(message):
            sent.append(message)
        scope = {'type': 'http', 'method': 'POST', 'path': '/mcp', 'query_string': b'',
                 'headers': [(b'host', b'verifiedpricing.com'), (b'authorization', b'Bearer x'),
                             (b'content-type', b'application/json')]}
        await self.app(scope, receive, send)
        self.assertEqual(self.app.body_readers, 0)
        self.assertEqual(self.app.active, 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.closed, 0)
        self.assertEqual(sent, [])

    async def test_complete_first_frame_bypasses_full_partial_pool(self):
        self.app.body_readers = self.app.body_readers_limit
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type': 'http.request', 'body': json.dumps(frame('tools/call')).encode(),
                        'more_body': False}
            await asyncio.Future()
        sent = []
        async def send(message):
            sent.append(message)
        scope = {'type': 'http', 'method': 'POST', 'path': '/mcp', 'query_string': b'',
                 'headers': [(k.lower().encode(), v.encode()) for k, v in
                             {**HEADERS, 'Host': 'verifiedpricing.com'}.items()]}
        try:
            await self.app(scope, receive, send)
            self.assertEqual(sent[0]['status'], 200)
            self.assertFalse(json.loads(sent[-1]['body'])['result']['isError'])
            self.assertEqual(self.app.body_readers, self.app.body_readers_limit)
            self.assertEqual(self.used[KEY], 1)
        finally:
            self.app.body_readers = 0

    async def test_genuine_tcp_sdk_succeeds_at_full_partial_body_pool(self):
        import uvicorn
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.listen(16)
        server = uvicorn.Server(uvicorn.Config(self.app, log_config=None, access_log=False,
                                  log_level='critical', lifespan='on', limit_concurrency=16))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        writers = []
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.005)
            for _ in range(self.app.body_readers_limit):
                _, writer = await asyncio.open_connection('127.0.0.1', port)
                writers.append(writer)
                writer.write(b'POST /mcp HTTP/1.1\r\nHost: verifiedpricing.com\r\n'
                             b'Authorization: Bearer x\r\nContent-Type: application/json\r\n'
                             b'Content-Length: 65536\r\n\r\n{')
                await writer.drain()
            for _ in range(100):
                if self.app.body_readers == self.app.body_readers_limit:
                    break
                await asyncio.sleep(0.005)
            self.assertEqual(self.app.body_readers, self.app.body_readers_limit)
            self.assertEqual(self.app.active, 0)
            self.assertEqual(self.calls, [])
            async with httpx2.AsyncClient(headers={**HEADERS, 'Host': 'verifiedpricing.com'},
                                           trust_env=False) as http:
                async with streamable_http_client(f'http://127.0.0.1:{port}/mcp', http_client=http) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        self.assertEqual(len((await session.list_tools()).tools), 11)
                        self.assertFalse((await session.call_tool('get_prices', {})).is_error)
            self.assertEqual(self.used[KEY], 1)
        finally:
            for writer in writers:
                writer.close()
            await asyncio.gather(*(writer.wait_closed() for writer in writers), return_exceptions=True)
            for _ in range(100):
                if self.app.body_readers == 0:
                    break
                await asyncio.sleep(0.005)
            server.should_exit = True
            await asyncio.wait_for(task, 2)
            listener.close()
        self.assertEqual(self.app.body_readers, 0)
