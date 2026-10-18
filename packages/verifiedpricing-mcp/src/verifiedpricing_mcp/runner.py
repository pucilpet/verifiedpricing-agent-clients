"""One actual blocking REST operation, with no executor submission backlog."""

import asyncio
import threading


class Busy(Exception):
    pass


class DeadlineExceeded(Exception):
    pass


class OperationFailed(Exception):
    pass


class SerialRunner:
    def __init__(self, deadline=12):
        if not 0 < deadline <= 60:
            raise ValueError("Invalid operation deadline")
        self.deadline = deadline
        self._permit = threading.Lock()
        self._closed = False

    @property
    def busy(self):
        return self._permit.locked()

    def close(self):
        self._closed = True

    async def run(self, operation):
        if self._closed or not self._permit.acquire(blocking=False):
            raise Busy()
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def finish(result, error):
            if not future.done():
                if error is None:
                    future.set_result(result)
                else:
                    # Retrieve even abandoned errors; never log exception contents.
                    future.set_exception(error)
                    future.exception()

        def work():
            result, error = None, None
            try:
                result = operation()
            except Exception as exc:
                error = exc
            finally:
                # Cancellation/deadline can abandon the await, never this actual-work permit.
                self._permit.release()
            try:
                loop.call_soon_threadsafe(finish, result, error)
            except RuntimeError:
                pass

        thread = threading.Thread(target=work, name="verifiedpricing-rest", daemon=True)
        try:
            thread.start()
        except RuntimeError:
            self._permit.release()
            raise OperationFailed() from None
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.deadline)
        except asyncio.TimeoutError:
            raise DeadlineExceeded() from None
