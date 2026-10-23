"""Real official SDK negotiation when installed; no mocked protocol acceptance."""

import asyncio
import importlib.util
import json
import os
import unittest
from contextlib import asynccontextmanager
import threading

from test_bounds import ENVELOPE, FakeClient

SDK_AVAILABLE = importlib.util.find_spec("mcp") is not None and importlib.util.find_spec("mcp_types") is not None


@unittest.skipUnless(SDK_AVAILABLE, "Official mcp==2.3.0 not installed; SDK protocol smoke remains pending")
class SDKTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def connection(self, client):
        from verifiedpricing_mcp.server import serve
        from verifiedpricing_mcp.transport import ready
        input_read, input_write = os.pipe()
        output_read, output_write = os.pipe()
        os.set_blocking(output_read, False)
        task = asyncio.create_task(serve(client, input_read, output_write))
        async def send(value):
            os.write(input_write, json.dumps(value).encode() + b"\n")
            await asyncio.sleep(0)
        async def receive():
            data = bytearray()
            while b"\n" not in data:
                try:
                    chunk = os.read(output_read, 4096)
                    if not chunk:
                        raise RuntimeError("Fixture pipe closed")
                    data.extend(chunk)
                except BlockingIOError:
                    await ready(output_read)
            return json.loads(data)
        try:
            yield send, receive
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for descriptor in (input_read, input_write, output_read, output_write):
                os.close(descriptor)

    async def test_official_sdk_modern_per_request_envelope(self):
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {"name": "private-fixture", "version": "0.1"}}
        async with self.connection(FakeClient()) as (send, receive):
            await send({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}})
            listed = await asyncio.wait_for(receive(), 3)
            self.assertEqual(len(listed["result"]["tools"]), 11)
            for tool in listed["result"]["tools"]:
                self.assertEqual(tool["annotations"]["readOnlyHint"], tool["name"] != "request_price_coverage")
                self.assertEqual(tool["annotations"]["idempotentHint"],
                                 tool["name"] in {"request_price_coverage", "get_price_coverage_request"})
                self.assertTrue(tool["annotations"]["openWorldHint"])
            await send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "_meta": meta, "name": "get_prices", "arguments": {}}})
            called = await asyncio.wait_for(receive(), 3)
            self.assertEqual(called["result"]["structuredContent"], ENVELOPE)

    async def test_official_sdk_competitor_tool_preserves_private_partial_response(self):
        envelope = {"schema_version": 1, "data": {"status": "partial", "reason": "synthetic_fixture",
            "seed": {"product_id": "product:example.com"}, "competitors": [],
            "discovery": {"edition": "fixture-2026-01"}, "comparison": {"status": "not_comparable"},
            "selection_policy": "synthetic only"}, "usage": {"day": {"used": 3}}}
        client = FakeClient(envelope)
        arguments = {"product_id": "product:example.com", "limit": 3, "competitor_product_id": "product:later.example",
                     "scenario": {"as_of": "2026-10-17T00:00:00Z", "currency": "USD", "market": "US"}}
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {}}
        async with self.connection(client) as (send, receive):
            await send({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "_meta": meta, "name": "get_competitor_prices", "arguments": arguments}})
            called = await asyncio.wait_for(receive(), 3)
            self.assertFalse(called["result"]["isError"])
            self.assertEqual(called["result"]["structuredContent"], envelope)
            self.assertEqual(client.calls, [("competitor_prices", (), arguments)])

    async def test_official_sdk_coverage_request_and_status_preserve_identity(self):
        request_id = "cr_" + "a" * 32
        envelope = {"schema_version": 1, "data": {"id": request_id, "status": "queued",
                    "domain": "product.example", "revision": 1}, "usage": {"day": {"used": 1}}}
        client = FakeClient(envelope)
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {}}
        async with self.connection(client) as (send, receive):
            arguments = {"domain": "product.example", "category": "seo", "consent": True}
            await send({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                "_meta": meta, "name": "request_price_coverage", "arguments": arguments}})
            requested = await asyncio.wait_for(receive(), 3)
            self.assertFalse(requested["result"]["isError"])
            self.assertEqual(requested["result"]["structuredContent"], envelope)
            await send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "_meta": meta, "name": "get_price_coverage_request", "arguments": {"request_id": request_id}}})
            status = await asyncio.wait_for(receive(), 3)
            self.assertFalse(status["result"]["isError"])
            self.assertEqual(status["result"]["structuredContent"], envelope)
        self.assertEqual(client.calls, [("request_price_coverage", (), arguments),
                                        ("price_coverage_request", (request_id,), {})])

    async def test_official_sdk_cancellation_cannot_start_replacement_http(self):
        started, release = threading.Event(), threading.Event()
        client = FakeClient()
        def blocked(*args, **kwargs):
            client.calls.append("actual_http")
            started.set()
            release.wait(2)
            return ENVELOPE
        client.prices = blocked
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {}}
        try:
            async with self.connection(client) as (send, receive):
                await send({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
                    "_meta": meta, "name": "get_prices", "arguments": {}}})
                for _ in range(100):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.005)
                self.assertTrue(started.is_set())
                await send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})
                await asyncio.sleep(0.03)
                await send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "_meta": meta, "name": "get_usage", "arguments": {}}})
                busy = await asyncio.wait_for(receive(), 3)
                self.assertEqual(busy["id"], 2)
                self.assertTrue(busy["result"]["isError"])
                self.assertEqual(busy["result"]["structuredContent"]["error"]["code"], "busy")
                self.assertEqual(client.calls, ["actual_http"])
        finally:
            release.set()

    async def test_official_sdk_handshake_tools_and_structured_snapshot(self):
        from importlib.metadata import version
        from verifiedpricing_mcp.server import serve
        from verifiedpricing_mcp.transport import ready
        self.assertEqual(version("mcp"), "2.3.0")
        input_read, input_write = os.pipe()
        output_read, output_write = os.pipe()
        os.set_blocking(output_read, False)
        task = asyncio.create_task(serve(FakeClient(), input_read, output_write))
        async def send(value):
            os.write(input_write, json.dumps(value).encode() + b"\n")
            await asyncio.sleep(0)
        async def receive():
            data = bytearray()
            while b"\n" not in data:
                try:
                    data.extend(os.read(output_read, 4096))
                except BlockingIOError:
                    await ready(output_read)
            return json.loads(data)
        try:
            await send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "private-fixture", "version": "0.1"}}})
            initialized = await asyncio.wait_for(receive(), 3)
            self.assertEqual(initialized["result"]["protocolVersion"], "2025-11-25")
            self.assertEqual(initialized["result"]["serverInfo"]["version"], "0.3.1")
            await send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            listed = await asyncio.wait_for(receive(), 3)
            self.assertEqual(len(listed["result"]["tools"]), 11)
            await send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_prices", "arguments": {}}})
            called = await asyncio.wait_for(receive(), 3)
            self.assertEqual(called["result"]["structuredContent"], ENVELOPE)
            self.assertFalse(called["result"]["isError"])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            for descriptor in (input_read, input_write, output_read, output_write):
                os.close(descriptor)
