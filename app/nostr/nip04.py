"""NIP-04 (legacy) encryption: AES-256-CBC keyed with the raw ECDH x-coordinate.

Kept only for compatibility with NIP-46 clients that still send NIP-04 payloads.
"""

from __future__ import annotations

import base64
import secrets

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .keys import shared_x


def is_nip04_payload(payload: str) -> bool:
    return "?iv=" in payload


def encrypt(plaintext: str, secret: bytes, pubkey_hex: str) -> str:
    key = shared_x(secret, pubkey_hex)
    iv = secrets.token_bytes(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = enc.update(padded) + enc.finalize()
    return f"{base64.b64encode(ciphertext).decode()}?iv={base64.b64encode(iv).decode()}"


def decrypt(payload: str, secret: bytes, pubkey_hex: str) -> str:
    ct_b64, iv_b64 = payload.split("?iv=", 1)
    key = shared_x(secret, pubkey_hex)
    dec = Cipher(algorithms.AES(key), modes.CBC(base64.b64decode(iv_b64))).decryptor()
    padded = dec.update(base64.b64decode(ct_b64)) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
