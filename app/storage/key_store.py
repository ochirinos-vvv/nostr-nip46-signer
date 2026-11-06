"""Persists Nostr secret keys in a JSON file, encrypted with a passphrase-derived key.

Format of `keys.json`:
    {"salt": "<b64>", "keys": {"<pubkey hex>": {"name", "created_at", "secret": "<fernet token>"}}}
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.nostr.keys import KeyPair


class KeyStoreError(Exception):
    pass


@dataclass(frozen=True)
class StoredKey:
    pubkey: str
    name: str
    created_at: int


class KeyStore:
    def __init__(self, path: Path, passphrase: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data = self._load()
        self._fernet = Fernet(self._derive_key(passphrase, base64.b64decode(self._data["salt"])))
        self._check_passphrase()

    # --- public API -------------------------------------------------------

    def add(self, keys: KeyPair, name: str) -> StoredKey:
        with self._lock:
            if keys.public_key_hex in self._data["keys"]:
                raise KeyStoreError("Key already stored")
            entry = {
                "name": name,
                "created_at": int(time.time()),
                "secret": self._fernet.encrypt(keys.secret).decode(),
            }
            self._data["keys"][keys.public_key_hex] = entry
            self._save()
        return StoredKey(keys.public_key_hex, entry["name"], entry["created_at"])

    def list(self) -> list[StoredKey]:
        return [StoredKey(pk, e["name"], e["created_at"]) for pk, e in self._data["keys"].items()]

    def get(self, pubkey: str) -> StoredKey | None:
        entry = self._data["keys"].get(pubkey)
        return StoredKey(pubkey, entry["name"], entry["created_at"]) if entry else None

    def load_keypair(self, pubkey: str) -> KeyPair:
        entry = self._data["keys"].get(pubkey)
        if entry is None:
            raise KeyStoreError("Unknown key")
        return KeyPair(self._fernet.decrypt(entry["secret"].encode()))

    def delete(self, pubkey: str) -> bool:
        with self._lock:
            if self._data["keys"].pop(pubkey, None) is None:
                return False
            self._save()
            return True

    # --- internals --------------------------------------------------------

    @staticmethod
    def _derive_key(passphrase: str, salt: bytes) -> bytes:
        raw = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())
        return base64.urlsafe_b64encode(raw)

    def _check_passphrase(self) -> None:
        try:
            for entry in self._data["keys"].values():
                self._fernet.decrypt(entry["secret"].encode())
                break
        except InvalidToken as exc:
            raise KeyStoreError("Passphrase does not match the stored keys") from exc

    def _load(self) -> dict:
        if self._path.exists():
            return json.loads(self._path.read_text(encoding="utf-8"))
        return {"salt": base64.b64encode(secrets.token_bytes(16)).decode(), "keys": {}}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic write
