import asyncio
import contextlib
import io
import json
import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from verifiedpricing_mcp.runner import Busy, DeadlineExceeded, SerialRunner
from verifiedpricing_mcp.tools import MAX_TEXT_BYTES, TOOLS, execute
from verifiedpricing_mcp.transport import (Admission, Framer, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES,
                                          ReadStream, TransportClosed, WriteStream, contains_secret)

ENVELOPE = {"schema_version": 1, "data": {"observations": [{"id": "po_" + "a" * 64,
    "product": "Fixture", "source_url": "https://fixture.example/pricing", "observed_at": "2026-10-17T00:00:00Z",
    "provenance": "automated", "trust_label": "Automated pricing source; not human verified"}],
    "next_offset": None}, "usage": {"day": {"used": 1}}}


class FakeClient:
    def __init__(self, result=ENVELOPE):
        self.result, self.calls = result, []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.result
        return call


class BoundsTests(unittest.TestCase):
    def test_framer_caps_before_decoding_and_handles_split_utf8(self):
        framer = Framer(maximum=8)
        framer.feed(b'"\xe2\x82')
        self.assertIsNone(framer.pop())
        framer.feed(b'\xac"\n{}\n')
        self.assertEqual(json.loads(framer.pop()), "€")
        self.assertEqual(json.loads(framer.pop()), {})
        with self.assertRaises(TransportClosed):
            framer.feed(b"a" * 9)

    def test_exact_frame_limit_and_many_frames_stay_bounded(self):
        framer = Framer(maximum=8)
        framer.feed(b"a" * 8 + b"\n")
        self.assertEqual(framer.pop(), b"a" * 8)
        for _ in range(100):
            framer.feed(b"{}\n")
            self.assertEqual(framer.pop(), b"{}")
        self.assertEqual(framer.buffer, b"")

    def test_immediate_request_admission_and_notification_bounds(self):
        admission = Admission()
        self.assertTrue(admission.accept({"method": "initialize", "id": 1}))
        with self.assertRaises(TransportClosed):
            admission.accept({"method": "tools/list", "id": 2})
        self.assertTrue(admission.accept({"method": "notifications/initialized"}))
        self.assertTrue(admission.accept({"method": "notifications/cancelled", "params": {"requestId": 1}}))
        self.assertFalse(admission.accept({"method": "notifications/cancelled", "params": {"requestId": 1}}))
        admission.release(1)
        self.assertTrue(admission.accept({"method": "tools/list", "id": 2}))
        with self.assertRaises(TransportClosed):
            for _ in range(40):
                admission.accept({"method": "notifications/progress", "params": {}})

    def test_secret_detection_checks_decoded_values_and_keys(self):
        self.assertTrue(contains_secret({"nested": [{"fixture_key": "value"}]}, "fixture_key"))
        self.assertFalse(contains_secret({"data": "public"}, "fixture_key"))


class LauncherVersionTests(unittest.TestCase):
    def test_candidate_launcher_requires_matching_client_before_opening_stdio(self):
        from verifiedpricing_mcp.cli import main
        for client_version,expected in (("0.1.0",2),("0.1.1",2),("0.1.2",2),("0.1.3",0)):
            with self.subTest(client_version=client_version):
                versions={"mcp":"2.3.0","verifiedpricing-client":client_version}
                with patch("verifiedpricing_mcp.cli.importlib.metadata.version",side_effect=versions.__getitem__), \
                     patch("verifiedpricing_mcp.cli.logging.disable"), \
                     patch.dict(os.environ,{"VERIFIEDPRICING_API_KEY":"vp_synthetic_candidate"}), \
                     patch("verifiedpricing_client.Client") as client, \
                     patch("verifiedpricing_mcp.server.serve",new_callable=AsyncMock) as serve, \
                     patch("verifiedpricing_mcp.transport.claim_stdio",return_value=contextlib.nullcontext((10,11))) as claim, \
                     contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main([]),expected)
                    if expected:
                        client.assert_not_called()
                        claim.assert_not_called()
                        serve.assert_not_called()
                    else:
                        client.assert_called_once_with("https://verifiedpricing.com","vp_synthetic_candidate",allow_localhost=False,timeout=15)
                        serve.assert_awaited_once_with(client.return_value,10,11,secret="vp_synthetic_candidate")

    def test_candidate_launcher_version_exits_before_dependency_checks(self):
        from verifiedpricing_mcp.cli import main
        output=io.StringIO()
        with patch("verifiedpricing_mcp.cli.importlib.metadata.version",side_effect=AssertionError("dependency lookup")), \
             contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as stopped:
            main(["--version"])
        self.assertEqual(stopped.exception.code,0)
        self.assertEqual(output.getvalue().strip(),"verifiedpricing-mcp 0.3.1")


class AsyncBoundsTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_retains_actual_work_permit(self):
        runner = SerialRunner(deadline=0.02)
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def work():
            started.set()
            release.wait(2)
            finished.set()
            return "done"
        try:
            with self.assertRaises(DeadlineExceeded):
                await runner.run(work)
            self.assertTrue(started.is_set())
            self.assertTrue(runner.busy)
            with self.assertRaises(Busy):
                await runner.run(lambda: None)
        finally:
            release.set()
            for _ in range(100):
                if finished.is_set() and not runner.busy:
                    break
                await asyncio.sleep(0.005)
        self.assertFalse(runner.busy)
        self.assertEqual(await runner.run(lambda: "next"), "next")

    async def test_cancelled_await_does_not_release_thread_permit(self):
        runner = SerialRunner(deadline=1)
        started, release = threading.Event(), threading.Event()
        def work():
            started.set()
            release.wait(2)
        task = asyncio.create_task(runner.run(work))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.005)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(runner.busy)
            with self.assertRaises(Busy):
                await runner.run(lambda: None)
        finally:
            release.set()
            for _ in range(100):
                if not runner.busy:
                    break
                await asyncio.sleep(0.005)
        self.assertFalse(runner.busy)

    async def test_tool_dispatch_preserves_envelope_and_does_not_upgrade_trust(self):
        client = FakeClient()
        runner = SerialRunner()
        payload, text, error = await execute(client, runner, "get_prices", {"limit": 2})
        self.assertIs(payload, ENVELOPE)
        self.assertFalse(error)
        self.assertIn("Automated observations are not human verification", text)
        self.assertIn("https://fixture.example/pricing", text)
        self.assertIn("2026-10-17", text)
        self.assertEqual(client.calls[0], ("prices", (None,), {"limit": 2, "offset": 0}))

    async def test_unknown_fields_credentials_origins_and_bad_scenarios_rejected_before_http(self):
        client = FakeClient()
        for name, args in (("get_usage", {"api_key": "secret"}), ("get_usage", {"base_url": "https://other.example"}),
                           ("get_prices", {"limit": True}), ("get_prices", {"offset": 10001}),
                           ("get_reviewed_records", {"domain": "valid.example", "provenance": "verified"}),
                           ("unknown", {}), ("get_prices", [])):
            payload, _, error = await execute(client, SerialRunner(), name, args)
            self.assertTrue(error)
            self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(client.calls, [])

    async def test_every_tool_has_a_fixed_bounded_surface(self):
        client = FakeClient()
        identifier = "po_" + "a" * 64
        second = "po_" + "b" * 64
        scenarios = {
            "search_products": {"query": "fixture"}, "get_prices": {}, "get_price": {"snapshot_id": identifier},
            "compare_prices": {"snapshot_ids": [identifier, second], "scenario": {
                "as_of": "2026-10-17T00:00:00Z", "currency": "USD", "market": "US", "usage_per_month": "0.125"}},
            "get_competitor_prices": {"product_id": "product:fixture.example", "scenario": {
                "as_of": "2026-10-17T00:00:00Z", "currency": "USD", "market": "US"}},
            "get_price_history": {"product_id": "fixture"}, "get_sources": {"snapshot_id": identifier},
            "get_reviewed_records": {"domain": "fixture.example"}, "get_usage": {},
            "request_price_coverage": {"product_id": "fixture", "consent": True},
            "get_price_coverage_request": {"request_id": "cr_" + "a" * 32},
        }
        self.assertEqual(set(scenarios), set(TOOLS))
        for name, arguments in scenarios.items():
            _, _, error = await execute(client, SerialRunner(), name, arguments)
            self.assertFalse(error, name)
        self.assertEqual(len(client.calls), 11)

    async def test_human_text_is_capped_but_structured_qualifications_preserved(self):
        envelope = {"schema_version": 1, "data": {"observations": [{"product": "x" * 12000,
                    "provenance": "automated", "source_url": "https://fixture.example/pricing"}]}, "usage": {}}
        payload, text, error = await execute(FakeClient(envelope), SerialRunner(), "get_prices", {})
        self.assertFalse(error)
        self.assertIs(payload, envelope)
        self.assertLessEqual(len(text.encode()), MAX_TEXT_BYTES)
        self.assertIn("Text truncated", text)

    async def test_read_pipe_caps_raw_frame_before_decode(self):
        read_fd, write_fd = os.pipe()
        decoded = []
        stream = ReadStream(read_fd, Admission(), lambda *args: decoded.append(args))
        async def write():
            os.set_blocking(write_fd, False)
            try:
                for _ in range(MAX_INPUT_BYTES // 4096 + 1):
                    while True:
                        try:
                            os.write(write_fd, b"x" * 4096)
                            break
                        except BlockingIOError:
                            await asyncio.sleep(0.001)
            finally:
                os.close(write_fd)
        writer = asyncio.create_task(write())
        try:
            with self.assertRaises(StopAsyncIteration):
                await stream.__anext__()
            self.assertEqual(decoded, [])
            self.assertTrue(stream.admission.closed_event.is_set())
        finally:
            await writer
            os.close(read_fd)

    async def test_output_caps_complete_frame_and_releases_only_after_write(self):
        import anyio
        read_fd, write_fd = os.pipe()
        admission = Admission()
        admission.accept({"id": 1, "method": "tools/list"})
        writer = WriteStream(write_fd, admission, secret="fixture_key")
        class Message:
            def __init__(self, value):
                self.value = value
            def model_dump(self, **kwargs):
                return self.value
        try:
            await writer.send(SimpleNamespace(message=Message({"jsonrpc": "2.0", "id": 1, "result": {}})))
            self.assertIsNone(admission.pending)
            self.assertEqual(json.loads(os.read(read_fd, 100)), {"jsonrpc": "2.0", "id": 1, "result": {}})
            for value in ({"result": {"key": "fixture_key"}}, {"result": "x" * MAX_OUTPUT_BYTES}):
                bounded_writer = WriteStream(write_fd, Admission(), secret="fixture_key")
                with self.assertRaises(anyio.BrokenResourceError):
                    await bounded_writer.send(SimpleNamespace(message=Message(value)))
        finally:
            os.close(read_fd)
            os.close(write_fd)

    async def test_stalled_stdout_has_whole_write_deadline_and_no_permit_release(self):
        import anyio
        read_fd, write_fd = os.pipe()
        admission = Admission()
        admission.accept({"id": 1, "method": "tools/call"})
        writer = WriteStream(write_fd, admission)
        message = SimpleNamespace(model_dump=lambda **kwargs: {"jsonrpc": "2.0", "id": 1, "result": "x" * 100000})
        try:
            with patch("verifiedpricing_mcp.transport.WRITE_SECONDS", 0.02):
                with self.assertRaises(anyio.BrokenResourceError):
                    await writer.send(SimpleNamespace(message=message))
            self.assertEqual(admission.pending, (int, 1))
            self.assertTrue(admission.closed_event.is_set())
        finally:
            os.close(read_fd)
            os.close(write_fd)
