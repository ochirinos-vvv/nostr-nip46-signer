"""NIP-46 remote signer ("bunker").

Spec: https://github.com/nostr-protocol/nips/blob/master/46.md

Transport: kind 24133 events, content = encrypted JSON-RPC-like message,
tagged with ["p", <recipient>]. We decrypt with NIP-44 and fall back to NIP-04 for
legacy clients, and always answer with the scheme the client used.

Authorization model (kept deliberately simple):
* A client becomes authorized by presenting a single-use `secret` in `connect`
  (bunker:// flow), or when the user pastes a nostrconnect:// URI (client-initiated flow).
* Authorized clients get every method auto-approved. There is no per-request approval UI.
* Authorizations live in memory: restarting the service forgets every client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse

from app.nostr import nip04, nip44
from app.nostr.event import Event, sign_event
from app.nostr.keys import KeyPair
from app.nostr.relay import RelayPool

log = logging.getLogger(__name__)

NIP46_KIND = 24133


class SignerError(Exception):
    pass


@dataclass
class Activity:
    at: int
    client: str
    method: str
    ok: bool
    detail: str = ""


@dataclass
class ClientSession:
    pubkey: str
    connected_at: int
    name: str | None = None
    via: str = "bunker"  # "bunker" | "nostrconnect"
    last_seen: int = field(default_factory=lambda: int(time.time()))


class RemoteSigner:
    def __init__(self, keys: KeyPair, relays: list[str], activity_size: int = 200,
                 pool_factory: Callable[..., RelayPool] = RelayPool) -> None:
        self.keys = keys
        self.pubkey = keys.public_key_hex
        self.relays = list(relays)
        self.pool = pool_factory(self.relays, keys, self._on_event)
        self.clients: dict[str, ClientSession] = {}
        self.activity: deque[Activity] = deque(maxlen=activity_size)
        self._pending_secrets: set[str] = set()
        self._lock = asyncio.Lock()

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self.pool.start()
        await self.pool.subscribe("nip46", {
            "kinds": [NIP46_KIND],
            "#p": [self.pubkey],
            "since": int(time.time()) - 60,
        })

    async def stop(self) -> None:
        await self.pool.stop()

    # --- connection flows -------------------------------------------------

    def new_bunker_uri(self) -> str:
        """bunker:// flow: the user pastes this URI in the client (e.g. Stacker News)."""
        secret = secrets.token_hex(16)
        self._pending_secrets.add(secret)
        params = "&".join(f"relay={quote(r, safe='')}" for r in self.relays)
        return f"bunker://{self.pubkey}?{params}&secret={secret}"

    async def accept_nostrconnect(self, uri: str) -> ClientSession:
        """nostrconnect:// flow: the client shows the URI, the signer initiates the connection."""
        parsed = urlparse(uri.strip())
        if parsed.scheme != "nostrconnect" or len(parsed.netloc) != 64:
            raise SignerError("Expected nostrconnect://<64-hex client pubkey>?relay=...&secret=...")
        client_pubkey = parsed.netloc.lower()
        query = parse_qs(parsed.query)
        relays = query.get("relay", [])
        secret = (query.get("secret") or [None])[0]
        if not relays or not secret:
            raise SignerError("nostrconnect URI must include at least one relay and a secret")

        session = ClientSession(client_pubkey, int(time.time()),
                                name=(query.get("name") or [None])[0], via="nostrconnect")
        self.clients[client_pubkey] = session
        await self.pool.add_relays(relays)
        response = {"id": secrets.token_hex(8), "result": secret}
        await self._send(client_pubkey, response, use_nip04=False)
        self._record(client_pubkey, "connect", True, "nostrconnect")
        return session

    def revoke(self, client_pubkey: str) -> bool:
        return self.clients.pop(client_pubkey, None) is not None

    # --- transport --------------------------------------------------------

    async def _on_event(self, event: Event) -> None:
        if event.get("kind") != NIP46_KIND:
            return
        if not any(t[:2] == ["p", self.pubkey] for t in event.get("tags", [])):
            return
        client = event["pubkey"]
        content = event["content"]
        use_nip04 = nip04.is_nip04_payload(content)
        try:
            if use_nip04:
                plaintext = nip04.decrypt(content, self.keys.secret, client)
            else:
                plaintext = nip44.decrypt(content, nip44.get_conversation_key(self.keys.secret, client))
            request = json.loads(plaintext)
        except Exception as exc:
            log.warning("Could not decrypt/parse NIP-46 request from %s: %s", client, exc)
            return
        if not isinstance(request, dict) or "id" not in request:
            return
        response = await self.handle_request(client, request)
        await self._send(client, response, use_nip04)

    async def _send(self, client_pubkey: str, message: dict, use_nip04: bool) -> None:
        plaintext = json.dumps(message)
        if use_nip04:
            content = nip04.encrypt(plaintext, self.keys.secret, client_pubkey)
        else:
            content = nip44.encrypt(plaintext, nip44.get_conversation_key(self.keys.secret, client_pubkey))
        event = sign_event(self.keys, NIP46_KIND, content, [["p", client_pubkey]])
        await self.pool.publish(event)

    # --- request handling (no I/O, unit-testable) -------------------------

    async def handle_request(self, client: str, request: dict[str, Any]) -> dict[str, Any]:
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or []
        async with self._lock:
            try:
                if method != "connect" and client not in self.clients:
                    raise SignerError("unauthorized: send connect with a valid secret first")
                result, detail = self._dispatch(client, method, params)
                if client in self.clients:
                    self.clients[client].last_seen = int(time.time())
                self._record(client, method, True, detail)
                return {"id": req_id, "result": result}
            except Exception as exc:
                self._record(client, method, False, str(exc))
                return {"id": req_id, "result": None, "error": str(exc)}

    def _dispatch(self, client: str, method: str, params: list) -> tuple[Any, str]:
        if method == "connect":
            return self._connect(client, params)
        if method == "get_public_key":
            return self.pubkey, ""
        if method == "ping":
            return "pong", ""
        if method == "sign_event":
            template = json.loads(params[0])
            event = sign_event(self.keys, int(template["kind"]), template.get("content", ""),
                               template.get("tags", []), template.get("created_at"))
            return json.dumps(event), f"kind {event['kind']}"
        if method in ("nip44_encrypt", "nip44_decrypt"):
            third_party, text = params[0], params[1]
            ck = nip44.get_conversation_key(self.keys.secret, third_party)
            fn = nip44.encrypt if method == "nip44_encrypt" else nip44.decrypt
            return fn(text, ck), ""
        if method == "nip04_encrypt":
            return nip04.encrypt(params[1], self.keys.secret, params[0]), ""
        if method == "nip04_decrypt":
            return nip04.decrypt(params[1], self.keys.secret, params[0]), ""
        if method == "get_relays":  # deprecated, still used by some clients
            return {r: {"read": True, "write": True} for r in self.relays}, ""
        raise SignerError(f"unsupported method: {method}")

    def _connect(self, client: str, params: list) -> tuple[str, str]:
        target = params[0] if params else None
        secret = params[1] if len(params) > 1 else None
        if target and target != self.pubkey:
            raise SignerError("connect targets a different signer")
        if client in self.clients:
            return "ack", "already authorized"
        if not secret or secret not in self._pending_secrets:
            raise SignerError("invalid or already used secret")
        self._pending_secrets.discard(secret)  # single use
        self.clients[client] = ClientSession(client, int(time.time()))
        return "ack", "bunker"

    def _record(self, client: str, method: str, ok: bool, detail: str = "") -> None:
        self.activity.appendleft(Activity(int(time.time()), client, method, ok, detail))

    # --- introspection ----------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {
            "pubkey": self.pubkey,
            "relays": self.pool.status(),
            "clients": [asdict(c) for c in self.clients.values()],
        }
