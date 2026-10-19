import asyncio


class MessageHub:
    def __init__(self):
        self.clients = set()
        self.lock = asyncio.Lock()

    async def register(self, ws) -> None:
        async with self.lock:
            self.clients.add(ws)

    async def unregister(self, ws) -> None:
        async with self.lock:
            self.clients.discard(ws)

    async def publish(self, item: dict) -> None:
        async with self.lock:
            clients = list(self.clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_json(item)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.unregister(ws)


hub = MessageHub()
