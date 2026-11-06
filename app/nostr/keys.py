"""Nostr key handling: generation, derivation and bech32 (NIP-19) encoding."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

import coincurve
from bech32 import bech32_decode, bech32_encode, convertbits


def _encode(hrp: str, data: bytes) -> str:
    return bech32_encode(hrp, convertbits(data, 8, 5))


def _decode(expected_hrp: str, value: str) -> bytes:
    hrp, data = bech32_decode(value)
    if hrp != expected_hrp or data is None:
        raise ValueError(f"Not a valid {expected_hrp} value")
    decoded = convertbits(data, 5, 8, False)
    if decoded is None or len(decoded) != 32:
        raise ValueError(f"Not a valid {expected_hrp} value")
    return bytes(decoded)


@dataclass(frozen=True)
class KeyPair:
    """A secp256k1 key pair. `public_key_hex` is the 32-byte x-only key used by Nostr."""

    secret: bytes

    def __post_init__(self) -> None:
        # Raises ValueError if the scalar is 0 or >= curve order.
        coincurve.PrivateKey(self.secret)

    @classmethod
    def generate(cls) -> "KeyPair":
        while True:
            try:
                return cls(secrets.token_bytes(32))
            except ValueError:  # astronomically unlikely invalid scalar
                continue

    @classmethod
    def from_any(cls, value: str) -> "KeyPair":
        """Accept an `nsec1...` string or a 64-char hex secret."""
        value = value.strip()
        if value.startswith("nsec1"):
            return cls(_decode("nsec", value))
        try:
            raw = bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("Secret key must be nsec1... or 64 hex characters") from exc
        if len(raw) != 32:
            raise ValueError("Secret key must be 32 bytes")
        return cls(raw)

    @property
    def private_key(self) -> coincurve.PrivateKey:
        return coincurve.PrivateKey(self.secret)

    @property
    def public_key_hex(self) -> str:
        return coincurve.PublicKeyXOnly.from_secret(self.secret).format().hex()

    @property
    def npub(self) -> str:
        return npub_from_hex(self.public_key_hex)

    @property
    def nsec(self) -> str:
        return _encode("nsec", self.secret)


def npub_from_hex(pubkey_hex: str) -> str:
    return _encode("npub", bytes.fromhex(pubkey_hex))


def hex_from_npub(npub: str) -> str:
    return _decode("npub", npub).hex()


def shared_x(secret: bytes, pubkey_hex: str) -> bytes:
    """Unhashed ECDH: x-coordinate of secret * P (P lifted with even y, as per BIP-340)."""
    point = coincurve.PublicKey(b"\x02" + bytes.fromhex(pubkey_hex))
    return point.multiply(secret).format(compressed=True)[1:]
