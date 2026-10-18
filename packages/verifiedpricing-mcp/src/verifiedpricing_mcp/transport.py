"""POSIX byte-bounded transport; the SDK still owns protocol negotiation."""

import asyncio
import contextlib
import json
import os

from .tools import bounded_json

MAX_INPUT_BYTES = 16384
READ_CHUNK_BYTES = 4096
MAX_OUTPUT_BYTES = 768 * 1024
MAX_DROPPED_NOTIFICATIONS = 32
FRAME_SECONDS = 10
WRITE_SECONDS = 5


class TransportClosed(Exception):
    pass


class Framer:
    def __init__(self, maximum=MAX_INPUT_BYTES):
        self.maximum = maximum
        self.buffer = bytearray()

    def feed(self, chunk):
        if len(chunk) > READ_CHUNK_BYTES:
            raise TransportClosed()
        self.buffer.extend(chunk)
        # A chunk can contain multiple short frames; retain at most one fixed chunk ahead.
        if len(self.buffer) > self.maximum + READ_CHUNK_BYTES:
            raise TransportClosed()
        position = self.buffer.find(b"\n")
        if position > self.maximum or (position < 0 and len(self.buffer) > self.maximum):
            raise TransportClosed()

    def pop(self):
        position = self.buffer.find(b"\n")
        if position < 0:
            return None
        if position > self.maximum:
            raise TransportClosed()
        frame = bytes(self.buffer[:position])
        del self.buffer[:position + 1]
        return frame


class Admission:
    """One request; at most initialized + one matching cancellation notification."""
    def __init__(self):
        self.pending = None
        self.initialized_seen = False
        self.cancel_seen = False
        self.dropped = 0
        self.closed_event = asyncio.Event()

    def accept(self, message):
        if not isinstance(message, dict) or not isinstance(message.get("method"), str):
            raise TransportClosed()
        if len(message["method"]) > 64:
            raise TransportClosed()
        if "id" in message:
            identifier = message["id"]
            if ((type(identifier) is not int or abs(identifier) > 2 ** 63 - 1)
                    and (not isinstance(identifier, str) or not 1 <= len(identifier) <= 64)):
                raise TransportClosed()
            if self.pending is not None:
                # No backlog of SDK handler tasks or busy-error replies.
                raise TransportClosed()
            self.pending = (type(identifier), identifier)
            self.cancel_seen = False
            self.dropped = 0
            return True
        method = message["method"]
        if method == "notifications/initialized" and not self.initialized_seen:
            self.initialized_seen = True
            return True
        if method == "notifications/cancelled" and not self.cancel_seen and self.pending is not None:
            params = message.get("params")
            identifier = params.get("requestId") if isinstance(params, dict) else None
            if (type(identifier), identifier) == self.pending:
                self.cancel_seen = True
                return True
        self.dropped += 1
        if self.dropped > MAX_DROPPED_NOTIFICATIONS:
            raise TransportClosed()
        return False

    def release(self, identifier):
        if self.pending == (type(identifier), identifier):
            self.pending = None


async def ready(descriptor, *, write=False):
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    def notify():
        if not future.done():
            future.set_result(None)
    add = loop.add_writer if write else loop.add_reader
    remove = loop.remove_writer if write else loop.remove_reader
    add(descriptor, notify)
    try:
        await future
    finally:
        remove(descriptor)


def contains_secret(value, secret):
    if not secret:
        return False
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


class StreamBase:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()


class ReadStream(StreamBase):
    def __init__(self, descriptor, admission, decode):
        super().__init__()
        self.descriptor, self.admission, self.decode = descriptor, admission, decode
        self.framer = Framer()
        os.set_blocking(descriptor, False)

    def __aiter__(self):
        return self

    async def __anext__(self):
        import anyio
        try:
            return await self.receive()
        except (TransportClosed, anyio.EndOfStream):
            raise StopAsyncIteration from None

    async def receive(self):
        import anyio
        if self.closed:
            raise anyio.EndOfStream
        try:
            while True:
                # Checkpoint even for a pipe permanently readable with notification spam.
                await asyncio.sleep(0)
                frame = await self._frame()
                try:
                    def reject_constant(value):
                        raise ValueError()
                    raw = json.loads(frame, parse_constant=reject_constant)
                except (ValueError, UnicodeError, RecursionError):
                    raise TransportClosed() from None
                if not self.admission.accept(raw):
                    continue
                try:
                    return self.decode(frame, raw.get("id"))
                except Exception:
                    raise TransportClosed() from None
        except (TransportClosed, OSError, TimeoutError):
            await self.aclose()
            self.admission.closed_event.set()
            raise anyio.EndOfStream from None

    async def _frame(self):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + FRAME_SECONDS if self.framer.buffer else None
        while True:
            frame = self.framer.pop()
            if frame is not None:
                return frame
            try:
                chunk = os.read(self.descriptor, READ_CHUNK_BYTES)
            except BlockingIOError:
                if deadline is None:
                    await ready(self.descriptor)
                else:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TransportClosed()
                    await asyncio.wait_for(ready(self.descriptor), remaining)
                continue
            if not chunk:
                raise TransportClosed()
            if deadline is None:
                deadline = loop.time() + FRAME_SECONDS
            self.framer.feed(chunk)


class WriteStream(StreamBase):
    def __init__(self, descriptor, admission, secret=None):
        super().__init__()
        self.descriptor, self.admission, self.secret = descriptor, admission, secret
        self.writing = False
        os.set_blocking(descriptor, False)

    async def send(self, session_message):
        import anyio
        if self.closed or self.writing:
            self.closed = True
            self.admission.closed_event.set()
            raise anyio.BrokenResourceError
        self.writing = True
        try:
            value = session_message.message.model_dump(mode="json", by_alias=True, exclude_unset=True)
            if contains_secret(value, self.secret):
                raise TransportClosed()
            encoded = bounded_json(value, MAX_OUTPUT_BYTES - 1) + b"\n"
            # No Python buffered stdout, send queue, or detached writer task.
            await asyncio.wait_for(self._write(encoded), WRITE_SECONDS)
            if "method" not in value and "id" in value:
                self.admission.release(value["id"])
        except (OSError, ValueError, TimeoutError, TransportClosed):
            self.closed = True
            self.admission.closed_event.set()
            raise anyio.BrokenResourceError from None
        except asyncio.CancelledError:
            # A partial JSON line must never be followed by another response.
            self.closed = True
            self.admission.closed_event.set()
            raise
        finally:
            self.writing = False

    async def _write(self, value):
        view = memoryview(value)
        while view:
            try:
                count = os.write(self.descriptor, view[:16384])
            except BlockingIOError:
                await ready(self.descriptor, write=True)
                continue
            if count <= 0:
                raise TransportClosed()
            view = view[count:]
            await asyncio.sleep(0)


@contextlib.contextmanager
def claim_stdio():
    """Private wire descriptors; accidental SDK/handler stdout misses the wire."""
    import fcntl
    input_fd = fcntl.fcntl(0, fcntl.F_DUPFD_CLOEXEC, 3)
    output_fd = fcntl.fcntl(1, fcntl.F_DUPFD_CLOEXEC, 3)
    input_blocking, output_blocking = os.get_blocking(input_fd), os.get_blocking(output_fd)
    diversion = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(diversion, 0)
        os.dup2(2, 1)
        yield input_fd, output_fd
    finally:
        os.set_blocking(input_fd, input_blocking)
        os.set_blocking(output_fd, output_blocking)
        os.dup2(input_fd, 0)
        os.dup2(output_fd, 1)
        os.close(diversion)
        os.close(input_fd)
        os.close(output_fd)
