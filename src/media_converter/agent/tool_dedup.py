import asyncio
import copy
import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass

from media_converter.common.errors import AppError, ErrorCode


def cache_key(context, name, arguments, data_version):
    payload = (
        context.instance_id,
        context.conversation_id,
        context.scope_version,
        context.settings_version,
        name,
        arguments,
        data_version,
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


@dataclass
class Flight:
    task: asyncio.Task
    subscribers: int = 0


class ToolDedup:
    def __init__(self, *, capacity=128, ttl=60):
        self.capacity, self.ttl = capacity, ttl
        self.cache, self.flights = OrderedDict(), {}
        self.backend_executions = 0

    async def call(self, key, factory, deadline):
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            self.cache.move_to_end(key)
            return copy.deepcopy(cached[1]), "hit"
        self.cache.pop(key, None)
        flight = self.flights.get(key)
        state = "merged" if flight else "miss"
        if flight is None:
            self.backend_executions += 1
            flight = Flight(asyncio.create_task(factory()))
            self.flights[key] = flight
        flight.subscribers += 1
        try:
            async with asyncio.timeout(max(0, deadline - time.time())):
                result = await asyncio.shield(flight.task)
            if result.get("ok") and key not in self.cache:
                self.cache[key] = (time.monotonic() + self.ttl, copy.deepcopy(result))
                while len(self.cache) > self.capacity:
                    self.cache.popitem(last=False)
            return copy.deepcopy(result), state
        except TimeoutError as error:
            raise AppError(ErrorCode.TIMEOUT) from error
        finally:
            flight.subscribers -= 1
            if flight.subscribers == 0:
                if self.flights.get(key) is flight:
                    self.flights.pop(key)
                if not flight.task.done():
                    flight.task.cancel()
                await asyncio.gather(flight.task, return_exceptions=True)

    async def close(self):
        tasks = [flight.task for flight in self.flights.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.flights.clear()
        self.cache.clear()
