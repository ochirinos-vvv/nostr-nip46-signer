from pydantic import BaseModel, Field

from app.nostr.keys import npub_from_hex
from app.storage.key_store import StoredKey


class CreateKeyRequest(BaseModel):
    secret: str | None = Field(
        default=None,
        description="nsec1... or 64-char hex. Omit to generate a new key.",
    )
    name: str | None = Field(default=None, max_length=64)


class KeyResponse(BaseModel):
    pubkey: str
    npub: str
    name: str
    created_at: int

    @classmethod
    def from_stored(cls, key: StoredKey) -> "KeyResponse":
        return cls(pubkey=key.pubkey, npub=npub_from_hex(key.pubkey),
                   name=key.name, created_at=key.created_at)


class BunkerResponse(BaseModel):
    bunker_uri: str = Field(description="Paste this in Stacker News > login with Nostr > bunker. Single use.")
    relays: list[str]


class NostrConnectRequest(BaseModel):
    uri: str = Field(description="nostrconnect://... URI shown by the client (e.g. as a QR code)")


class ClientSessionResponse(BaseModel):
    pubkey: str
    connected_at: int
    last_seen: int
    name: str | None
    via: str


class SignerStatusResponse(BaseModel):
    pubkey: str
    relays: dict[str, bool]
    clients: list[ClientSessionResponse]


class ActivityResponse(BaseModel):
    at: int
    client: str
    method: str
    ok: bool
    detail: str
