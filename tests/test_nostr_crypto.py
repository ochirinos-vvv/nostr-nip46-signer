import pytest

from app.nostr import nip04, nip44
from app.nostr.event import sign_event, verify_event
from app.nostr.keys import KeyPair, hex_from_npub


def test_nip44_spec_vector():
    # First vector from the NIP-44 v2 spec test suite.
    sec1 = bytes.fromhex("00" * 31 + "01")
    pub2 = KeyPair(bytes.fromhex("00" * 31 + "02")).public_key_hex
    ck = nip44.get_conversation_key(sec1, pub2)
    assert ck.hex() == "c41c775356fd92eadc63ff5a0dc1da211b268cbea22316767095b2871ea1412d"
    payload = nip44.encrypt("a", ck, bytes.fromhex("00" * 31 + "01"))
    assert payload == ("AgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABee0G5VSK0/9YypIObAtDKfYEAjD35uVk"
                       "HyB0F4DwrcNaCXlCWZKaArsGrY6M9wnuTMxWfp1RTN9Xga8no+kF5Vsb")
    assert nip44.decrypt(payload, ck) == "a"


@pytest.mark.parametrize("text", ["x", "hola 👋", "a" * 33, "b" * 1000])
def test_nip44_roundtrip_is_symmetric(text):
    a, b = KeyPair.generate(), KeyPair.generate()
    payload = nip44.encrypt(text, nip44.get_conversation_key(a.secret, b.public_key_hex))
    assert nip44.decrypt(payload, nip44.get_conversation_key(b.secret, a.public_key_hex)) == text


def test_nip44_rejects_tampered_payload():
    a, b = KeyPair.generate(), KeyPair.generate()
    ck = nip44.get_conversation_key(a.secret, b.public_key_hex)
    payload = nip44.encrypt("secret", ck)
    tampered = payload[:-5] + ("A" if payload[-5] != "A" else "B") + payload[-4:]
    with pytest.raises(ValueError):
        nip44.decrypt(tampered, ck)


def test_nip04_roundtrip():
    a, b = KeyPair.generate(), KeyPair.generate()
    payload = nip04.encrypt("hola", a.secret, b.public_key_hex)
    assert nip04.is_nip04_payload(payload)
    assert nip04.decrypt(payload, b.secret, a.public_key_hex) == "hola"


def test_sign_and_verify_event():
    keys = KeyPair.generate()
    event = sign_event(keys, 1, "hello", [["t", "test"]])
    assert verify_event(event)
    assert not verify_event({**event, "content": "changed"})


def test_key_encodings_roundtrip():
    keys = KeyPair.generate()
    assert KeyPair.from_any(keys.nsec).secret == keys.secret
    assert KeyPair.from_any(keys.secret.hex()).secret == keys.secret
    assert hex_from_npub(keys.npub) == keys.public_key_hex
    with pytest.raises(ValueError):
        KeyPair.from_any("not-a-key")
