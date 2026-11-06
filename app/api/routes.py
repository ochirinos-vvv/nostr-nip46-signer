from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.schemas import (
    ActivityResponse,
    BunkerResponse,
    ClientSessionResponse,
    CreateKeyRequest,
    KeyResponse,
    NostrConnectRequest,
    SignerStatusResponse,
)
from app.services import NotFound, SignerService
from app.signer.remote_signer import RemoteSigner, SignerError
from app.storage.key_store import KeyStoreError

router = APIRouter(prefix="/api")


def get_service(request: Request) -> SignerService:
    return request.app.state.signer_service


def get_signer(pubkey: str, service: SignerService = Depends(get_service)) -> RemoteSigner:
    try:
        return service.signer(pubkey)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- keys -----------------------------------------------------------------

@router.post("/keys", status_code=status.HTTP_201_CREATED, response_model=KeyResponse)
async def create_key(body: CreateKeyRequest, service: SignerService = Depends(get_service)):
    """Import an existing secret key (nsec/hex) or generate a new one.

    The secret is never returned by the API: it stays inside the signer.
    """
    try:
        stored = await service.create_key(body.secret, body.name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except KeyStoreError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return KeyResponse.from_stored(stored)


@router.get("/keys", response_model=list[KeyResponse])
def list_keys(service: SignerService = Depends(get_service)):
    return [KeyResponse.from_stored(k) for k in service.list_keys()]


@router.delete("/keys/{pubkey}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(pubkey: str, service: SignerService = Depends(get_service)):
    try:
        await service.delete_key(pubkey)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- NIP-46 signer ----------------------------------------------------------

@router.post("/keys/{pubkey}/bunker", response_model=BunkerResponse)
def create_bunker_uri(signer: RemoteSigner = Depends(get_signer)):
    """Generate a single-use bunker:// URI for this key (signer-initiated flow)."""
    return BunkerResponse(bunker_uri=signer.new_bunker_uri(), relays=signer.relays)


@router.post("/keys/{pubkey}/nostrconnect", response_model=ClientSessionResponse)
async def accept_nostrconnect(body: NostrConnectRequest, signer: RemoteSigner = Depends(get_signer)):
    """Accept a nostrconnect:// URI shown by a client (client-initiated flow)."""
    try:
        session = await signer.accept_nostrconnect(body.uri)
    except SignerError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return ClientSessionResponse(**asdict(session))


@router.get("/keys/{pubkey}/status", response_model=SignerStatusResponse)
def signer_status(signer: RemoteSigner = Depends(get_signer)):
    """Relay connectivity and authorized client sessions."""
    return signer.status()


@router.delete("/keys/{pubkey}/clients/{client_pubkey}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_client(client_pubkey: str, signer: RemoteSigner = Depends(get_signer)):
    if not signer.revoke(client_pubkey):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Client not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/keys/{pubkey}/activity", response_model=list[ActivityResponse])
def signer_activity(signer: RemoteSigner = Depends(get_signer)):
    """Most recent NIP-46 requests handled by this signer (newest first)."""
    return [asdict(a) for a in signer.activity]
