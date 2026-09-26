"""In-memory stand-ins for the bits of aio_pika the runner and brain use."""
import asyncio
import json
from contextlib import asynccontextmanager


class FakeMessage:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.acked = False
        self.rejected = False

    @asynccontextmanager
    async def process(self):
        # like aio_pika: ack on clean exit, reject and re-raise on exception
        try:
            yield
        except BaseException:
            self.rejected = True
            raise
        self.acked = True


class FakeQueue:
    def __init__(self, name):
        self.name = name
        self._q = asyncio.Queue()

    def put(self, body):
        msg = FakeMessage(body)
        self._q.put_nowait(msg)
        return msg

    def close(self):
        # ends any iterator once the queued messages are drained
        self._q.put_nowait(None)

    def iterator(self):
        return _FakeIterator(self._q)


class _FakeIterator:
    def __init__(self, q):
        self._q = q

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        msg = await self._q.get()
        if msg is None:
            raise StopAsyncIteration
        return msg


class FakeExchange:
    def __init__(self, on_publish=None):
        self.published = []  # (routing_key, decoded body)
        self.on_publish = on_publish

    async def publish(self, message, routing_key):
        body = json.loads(message.body)
        self.published.append((routing_key, body))
        if self.on_publish:
            self.on_publish(routing_key, body)


class FakeChannel:
    def __init__(self):
        self.default_exchange = FakeExchange()
        self.queues = {}

    def queue(self, name):
        return self.queues.setdefault(name, FakeQueue(name))

    async def declare_queue(self, name, durable=False):
        return self.queue(name)

    async def set_qos(self, prefetch_count):
        pass


class FakeConnection:
    def __init__(self, channel):
        self._channel = channel

    async def channel(self):
        return self._channel

    async def close(self):
        pass
