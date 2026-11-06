"""Minimal Nostr relay client (NIP-01) with reconnection and NIP-42 AUTH."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections import OrderedDict
from typing import Awaitable, Callable

import truststore
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidURI

from .event import Event, sign_event, verify_event
from .keys import KeyPair

log = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]

# Uses the OS certificate store (works behind corporate TLS-inspecting proxies).
_SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class RelayClient:
    """One persistent connection to a relay. Re-sends subscriptions after reconnecting."""

    def __init__(self, url: str, keys: KeyPair, on_event: EventHandler) -> None:
        self.url = url
        self._keys = keys  # used only to answer NIP-42 AUTH challenges
        self._on_event = on_event
        self._subs: dict[str, dict] = {}
        self._ws: ClientConnection | None = None
        self._task: asyncio.Task | None = None
        self.connected = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"relay:{self.url}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.connected.clear()

    async def subscribe(self, sub_id: str, filter_: dict) -> None:
        self._subs[sub_id] = filter_
        await self._send(["REQ", sub_id, filter_])

    async def publish(self, event: Event, timeout: float = 10) -> None:
        try:
            await asyncio.wait_for(self.connected.wait(), timeout)
        except asyncio.TimeoutError:
            log.warning("Not connected to %s, event %s dropped", self.url, event["id"])
            return
        await self._send(["EVENT", event])

    async def _send(self, message: list) -> None:
        if self._ws is None:
            return  # subscriptions are re-sent on (re)connect
        try:
            await self._ws.send(json.dumps(message))
        except ConnectionClosed:
            log.warning("Send failed, %s is disconnected", self.url)

    async def _run(self) -> None:
        backoff = 1
        while True:
            try:
                async with connect(self.url, ssl=_SSL_CONTEXT if self.url.startswith("wss") else None,
                                   open_timeout=10) as ws:
                    self._ws = ws
                    self.connected.set()
                    backoff = 1
                    log.info("Connected to %s", self.url)
                    for sub_id, filter_ in self._subs.items():
                        await self._send(["REQ", sub_id, filter_])
                    async for raw in ws:
                        await self._handle(raw)
            except asyncio.CancelledError:
                raise
            except InvalidURI:
                log.error("Invalid relay URL %s, giving up", self.url)
                return
            except Exception as exc:  # network errors: log and retry
                log.warning("Relay %s error: %s", self.url, exc)
            finally:
                self._ws = None
                self.connected.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _handle(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, list) or not msg:
            return
        kind = msg[0]
        if kind == "EVENT" and len(msg) >= 3 and isinstance(msg[2], dict):
            event = msg[2]
            if verify_event(event):
                await self._on_event(event)
        elif kind == "AUTH" and len(msg) >= 2:
            auth = sign_event(self._keys, 22242, "",
                              [["relay", self.url], ["challenge", str(msg[1])]])
            await self._send(["AUTH", auth])
        elif kind == "CLOSED" and len(msg) >= 3 and str(msg[2]).startswith("auth-required"):
            # Re-request once the relay has processed our AUTH.
            sub_id = msg[1]
            if sub_id in self._subs:
                await asyncio.sleep(1)
                await self._send(["REQ", sub_id, self._subs[sub_id]])
        elif kind == "OK" and len(msg) >= 4 and msg[2] is False:
            log.warning("Relay %s rejected event %s: %s", self.url, msg[1], msg[3])
        elif kind == "NOTICE":
            log.info("NOTICE from %s: %s", self.url, msg[1:])


class RelayPool:
    """Fan-out to several relays; events received from more than one relay are deduplicated."""

    def __init__(self, urls: list[str], keys: KeyPair, on_event: EventHandler) -> None:
        self._keys = keys
        self._on_event = on_event
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._subs: dict[str, dict] = {}
        self._started = False
        self.relays = [RelayClient(u, keys, self._dedupe) for u in dict.fromkeys(urls)]

    async def add_relays(self, urls: list[str]) -> None:
        """Connect to extra relays (e.g. the ones a nostrconnect:// client asked for)."""
        known = {r.url for r in self.relays}
        for url in urls:
            if url in known:
                continue
            relay = RelayClient(url, self._keys, self._dedupe)
            self.relays.append(relay)
            known.add(url)
            for sub_id, filter_ in self._subs.items():
                await relay.subscribe(sub_id, filter_)
            if self._started:
                relay.start()

    async def _dedupe(self, event: Event) -> None:
        if event["id"] in self._seen:
            return
        self._seen[event["id"]] = None
        if len(self._seen) > 5000:
            self._seen.popitem(last=False)
        await self._on_event(event)

    def start(self) -> None:
        self._started = True
        for relay in self.relays:
            relay.start()

    async def stop(self) -> None:
        await asyncio.gather(*(r.stop() for r in self.relays))

    async def wait_connected(self, timeout: float = 10) -> bool:
        """Wait until at least one relay is connected."""
        waits = [asyncio.create_task(r.connected.wait()) for r in self.relays]
        done, pending = await asyncio.wait(waits, timeout=timeout,
                                           return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        return bool(done)

    async def subscribe(self, sub_id: str, filter_: dict) -> None:
        self._subs[sub_id] = filter_
        await asyncio.gather(*(r.subscribe(sub_id, filter_) for r in self.relays))

    async def publish(self, event: Event) -> None:
        await asyncio.gather(*(r.publish(event) for r in self.relays))

    def status(self) -> dict[str, bool]:
        return {r.url: r.connected.is_set() for r in self.relays}
