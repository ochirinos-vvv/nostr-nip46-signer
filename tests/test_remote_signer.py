import json
from urllib.parse import parse_qs, urlparse

import pytest

from app.nostr import nip04, nip44
from app.nostr.event import sign_event, verify_event
from app.nostr.keys import KeyPair
from app.signer.remote_signer import NIP46_KIND, RemoteSigner


@pytest.fixture
def signer(fake_pool):
    return RemoteSigner(KeyPair.generate(), ["wss://relay.example"], pool_factory=fake_pool)


def bunker_secret(uri: str) -> str:
    return parse_qs(urlparse(uri).query)["secret"][0]


class Client:
    """Simulates a NIP-46 client such as Stacker News talking to the signer over a relay."""

    def __init__(self, signer: RemoteSigner, legacy_nip04: bool = False):
        self.keys = KeyPair.generate()
        self.signer = signer
        self.legacy = legacy_nip04
        self._n = 0

    async def call(self, method: str, params: list) -> dict:
        self._n += 1
        plaintext = json.dumps({"id": str(self._n), "method": method, "params": params})
        if self.legacy:
            content = nip04.encrypt(plaintext, self.keys.secret, self.signer.pubkey)
        else:
            ck = nip44.get_conversation_key(self.keys.secret, self.signer.pubkey)
            content = nip44.encrypt(plaintext, ck)
        await self.signer._on_event(
            sign_event(self.keys, NIP46_KIND, content, [["p", self.signer.pubkey]]))
        reply = self.signer.pool.published[-1]
        assert reply["kind"] == NIP46_KIND and ["p", self.keys.public_key_hex] in reply["tags"]
        assert verify_event(reply)
        return json.loads(self.decrypt(reply["content"]))

    def decrypt(self, content: str) -> str:
        if self.legacy:
            return nip04.decrypt(content, self.keys.secret, self.signer.pubkey)
        return nip44.decrypt(content, nip44.get_conversation_key(self.keys.secret, self.signer.pubkey))


@pytest.mark.parametrize("legacy", [False, True])
async def test_bunker_login_flow(signer, legacy):
    """connect -> get_public_key -> sign_event, which is what a 'login with Nostr' does."""
    uri = signer.new_bunker_uri()
    assert uri.startswith(f"bunker://{signer.pubkey}?relay=")
    client = Client(signer, legacy_nip04=legacy)

    assert (await client.call("connect", [signer.pubkey, bunker_secret(uri)]))["result"] == "ack"
    assert (await client.call("get_public_key", []))["result"] == signer.pubkey

    template = {"kind": 27235, "content": "", "tags": [["challenge", "abc"]], "created_at": 1700000000}
    signed = json.loads((await client.call("sign_event", [json.dumps(template)]))["result"])
    assert verify_event(signed)
    assert signed["pubkey"] == signer.pubkey
    assert signed["tags"] == template["tags"] and signed["created_at"] == 1700000000
    assert [a.method for a in signer.activity][:3] == ["sign_event", "get_public_key", "connect"]


async def test_requests_before_connect_are_rejected(signer):
    response = await Client(signer).call("sign_event", [json.dumps({"kind": 1, "content": "x"})])
    assert response["result"] is None and "unauthorized" in response["error"]


async def test_bunker_secret_is_single_use(signer):
    secret = bunker_secret(signer.new_bunker_uri())
    assert (await Client(signer).call("connect", [signer.pubkey, secret]))["result"] == "ack"
    second = await Client(signer).call("connect", [signer.pubkey, secret])
    assert "invalid" in second["error"]


async def test_wrong_secret_is_rejected(signer):
    signer.new_bunker_uri()
    response = await Client(signer).call("connect", [signer.pubkey, "wrong"])
    assert response["error"]


async def test_nostrconnect_flow(signer):
    client = Client(signer)
    uri = (f"nostrconnect://{client.keys.public_key_hex}"
           "?relay=wss%3A%2F%2Fclient.relay&secret=s3cr3t&name=Stacker%20News")
    session = await signer.accept_nostrconnect(uri)
    assert session.name == "Stacker News"
    assert "wss://client.relay" in signer.pool.urls

    connect_reply = json.loads(client.decrypt(signer.pool.published[-1]["content"]))
    assert connect_reply["result"] == "s3cr3t"
    assert (await client.call("get_public_key", []))["result"] == signer.pubkey


async def test_events_for_other_signers_are_ignored(signer):
    other = KeyPair.generate()
    event = sign_event(KeyPair.generate(), NIP46_KIND, "x", [["p", other.public_key_hex]])
    await signer._on_event(event)
    assert signer.pool.published == []
