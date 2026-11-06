"""NIP-44 v2 encryption (ChaCha20 + HMAC-SHA256, HKDF key derivation, padding).

Spec: https://github.com/nostr-protocol/nips/blob/master/44.md
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import secrets

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

from .keys import shared_x

VERSION = 2
MIN_PLAINTEXT = 1
MAX_PLAINTEXT = 65535


def get_conversation_key(secret: bytes, pubkey_hex: str) -> bytes:
    # HKDF-extract(salt="nip44-v2", ikm=shared_x)
    return hmac.new(b"nip44-v2", shared_x(secret, pubkey_hex), hashlib.sha256).digest()


def _message_keys(conversation_key: bytes, nonce: bytes) -> tuple[bytes, bytes, bytes]:
    # HKDF-expand(prk=conversation_key, info=nonce, L=76)
    okm, block = b"", b""
    counter = 1
    while len(okm) < 76:
        block = hmac.new(conversation_key, block + nonce + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[0:32], okm[32:44], okm[44:76]


def _padded_len(unpadded: int) -> int:
    if unpadded <= 32:
        return 32
    next_power = 1 << (math.floor(math.log2(unpadded - 1)) + 1)
    chunk = 32 if next_power <= 256 else next_power // 8
    return chunk * (math.floor((unpadded - 1) / chunk) + 1)


def _pad(plaintext: str) -> bytes:
    raw = plaintext.encode("utf-8")
    if not MIN_PLAINTEXT <= len(raw) <= MAX_PLAINTEXT:
        raise ValueError("Invalid plaintext length")
    return len(raw).to_bytes(2, "big") + raw + b"\x00" * (_padded_len(len(raw)) - len(raw))


def _unpad(padded: bytes) -> str:
    length = int.from_bytes(padded[:2], "big")
    raw = padded[2:2 + length]
    if length < MIN_PLAINTEXT or len(raw) != length or len(padded) != 2 + _padded_len(length):
        raise ValueError("Invalid padding")
    return raw.decode("utf-8")


def _chacha20(key: bytes, nonce12: bytes, data: bytes) -> bytes:
    # `cryptography` takes a 16-byte nonce: 4-byte little-endian counter (0) + 12-byte nonce.
    cipher = Cipher(algorithms.ChaCha20(key, b"\x00" * 4 + nonce12), mode=None)
    return cipher.encryptor().update(data)


def encrypt(plaintext: str, conversation_key: bytes, nonce: bytes | None = None) -> str:
    nonce = nonce or secrets.token_bytes(32)
    chacha_key, chacha_nonce, hmac_key = _message_keys(conversation_key, nonce)
    ciphertext = _chacha20(chacha_key, chacha_nonce, _pad(plaintext))
    mac = hmac.new(hmac_key, nonce + ciphertext, hashlib.sha256).digest()
    return base64.b64encode(bytes([VERSION]) + nonce + ciphertext + mac).decode()


def decrypt(payload: str, conversation_key: bytes) -> str:
    if not payload or payload[0] == "#":
        raise ValueError("Unknown encryption version")
    if not 132 <= len(payload) <= 87472:
        raise ValueError("Invalid payload size")
    data = base64.b64decode(payload, validate=True)
    if data[0] != VERSION:
        raise ValueError(f"Unknown encryption version {data[0]}")
    nonce, ciphertext, mac = data[1:33], data[33:-32], data[-32:]
    chacha_key, chacha_nonce, hmac_key = _message_keys(conversation_key, nonce)
    expected = hmac.new(hmac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("Invalid MAC")
    return _unpad(_chacha20(chacha_key, chacha_nonce, ciphertext))
