"""Nostr events (NIP-01): canonical serialization, id, Schnorr signature."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

import coincurve

from .keys import KeyPair

Event = dict[str, Any]


def event_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    serialized = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def sign_event(keys: KeyPair, kind: int, content: str, tags: list | None = None,
               created_at: int | None = None) -> Event:
    tags = tags or []
    created_at = int(time.time()) if created_at is None else int(created_at)
    pubkey = keys.public_key_hex
    eid = event_id(pubkey, created_at, kind, tags, content)
    sig = keys.private_key.sign_schnorr(bytes.fromhex(eid), secrets.token_bytes(32))
    return {
        "id": eid,
        "pubkey": pubkey,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig.hex(),
    }


def verify_event(event: Event) -> bool:
    try:
        expected = event_id(event["pubkey"], event["created_at"], event["kind"],
                            event["tags"], event["content"])
        if expected != event["id"]:
            return False
        pub = coincurve.PublicKeyXOnly(bytes.fromhex(event["pubkey"]))
        return pub.verify(bytes.fromhex(event["sig"]), bytes.fromhex(event["id"]))
    except (KeyError, ValueError, TypeError):
        return False
