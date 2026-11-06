"""Application service: ties the encrypted key store to one running NIP-46 signer per key."""

from __future__ import annotations

from typing import Callable

from app.nostr.keys import KeyPair, hex_from_npub
from app.nostr.relay import RelayPool
from app.signer.remote_signer import RemoteSigner
from app.storage.key_store import KeyStore, StoredKey


class NotFound(Exception):
    pass


def normalize_pubkey(value: str) -> str:
    """Accept npub1... or 64-char hex."""
    value = value.strip()
    if value.startswith("npub1"):
        return hex_from_npub(value)
    if len(value) == 64:
        bytes.fromhex(value)
        return value.lower()
    raise ValueError("Public key must be npub1... or 64 hex characters")


class SignerService:
    def __init__(self, store: KeyStore, relays: list[str], activity_size: int = 200,
                 pool_factory: Callable[..., RelayPool] = RelayPool) -> None:
        self._store = store
        self._relays = relays
        self._activity_size = activity_size
        self._pool_factory = pool_factory
        self._signers: dict[str, RemoteSigner] = {}

    async def startup(self) -> None:
        for stored in self._store.list():
            await self._start_signer(self._store.load_keypair(stored.pubkey))

    async def shutdown(self) -> None:
        for signer in self._signers.values():
            await signer.stop()
        self._signers.clear()

    # --- keys -------------------------------------------------------------

    async def create_key(self, secret: str | None, name: str | None) -> StoredKey:
        keys = KeyPair.from_any(secret) if secret else KeyPair.generate()
        stored = self._store.add(keys, name or f"key-{keys.npub[5:13]}")
        await self._start_signer(keys)
        return stored

    def list_keys(self) -> list[StoredKey]:
        return self._store.list()

    def get_key(self, pubkey: str) -> StoredKey:
        stored = self._store.get(normalize_pubkey(pubkey))
        if stored is None:
            raise NotFound("Key not found")
        return stored

    async def delete_key(self, pubkey: str) -> None:
        pubkey = normalize_pubkey(pubkey)
        if not self._store.delete(pubkey):
            raise NotFound("Key not found")
        signer = self._signers.pop(pubkey, None)
        if signer:
            await signer.stop()

    # --- signer -----------------------------------------------------------

    def signer(self, pubkey: str) -> RemoteSigner:
        signer = self._signers.get(normalize_pubkey(pubkey))
        if signer is None:
            raise NotFound("Key not found")
        return signer

    async def _start_signer(self, keys: KeyPair) -> None:
        signer = RemoteSigner(keys, self._relays, self._activity_size, self._pool_factory)
        self._signers[keys.public_key_hex] = signer
        await signer.start()
