import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.nostr.keys import KeyPair
from app.storage.key_store import KeyStore, KeyStoreError


@pytest.fixture
def client(settings, fake_pool):
    with TestClient(create_app(settings, pool_factory=fake_pool)) as c:
        yield c


def test_ui_is_served_and_api_still_wins(client):
    page = client.get("/")
    assert page.status_code == 200 and "Firmante NIP-46" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}


def test_generate_and_list_keys(client):
    created = client.post("/api/keys", json={"name": "demo"}).json()
    assert created["npub"].startswith("npub1") and "secret" not in created
    assert [k["pubkey"] for k in client.get("/api/keys").json()] == [created["pubkey"]]


def test_import_key_by_nsec(client):
    keys = KeyPair.generate()
    created = client.post("/api/keys", json={"secret": keys.nsec}).json()
    assert created["pubkey"] == keys.public_key_hex
    assert client.post("/api/keys", json={"secret": keys.nsec}).status_code == 409


def test_invalid_secret_is_422(client):
    assert client.post("/api/keys", json={"secret": "nope"}).status_code == 422


def test_bunker_uri_status_and_delete(client):
    key = client.post("/api/keys", json={}).json()
    bunker = client.post(f"/api/keys/{key['npub']}/bunker").json()
    assert bunker["bunker_uri"].startswith(f"bunker://{key['pubkey']}")
    status = client.get(f"/api/keys/{key['pubkey']}/status").json()
    assert status["relays"] == {"wss://relay.example": True} and status["clients"] == []
    assert client.get(f"/api/keys/{key['pubkey']}/activity").json() == []

    assert client.delete(f"/api/keys/{key['pubkey']}").status_code == 204
    assert client.post(f"/api/keys/{key['pubkey']}/bunker").status_code == 404


def test_invalid_nostrconnect_uri(client):
    key = client.post("/api/keys", json={}).json()
    r = client.post(f"/api/keys/{key['pubkey']}/nostrconnect", json={"uri": "https://x"})
    assert r.status_code == 422


def test_keys_are_encrypted_at_rest_and_survive_restart(settings, tmp_path):
    keys = KeyPair.generate()
    store = KeyStore(tmp_path / "keys.json", "pass")
    store.add(keys, "k")
    raw = (tmp_path / "keys.json").read_text()
    assert keys.secret.hex() not in raw and keys.nsec not in raw

    assert KeyStore(tmp_path / "keys.json", "pass").load_keypair(keys.public_key_hex).secret == keys.secret
    with pytest.raises(KeyStoreError):
        KeyStore(tmp_path / "keys.json", "wrong")
