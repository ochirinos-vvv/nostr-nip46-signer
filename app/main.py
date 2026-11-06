import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import Settings, get_settings
from app.services import SignerService
from app.storage.key_store import KeyStore


def create_app(settings: Settings | None = None, pool_factory=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = KeyStore(settings.data_dir / "keys.json", settings.passphrase.get_secret_value())
        kwargs = {"pool_factory": pool_factory} if pool_factory else {}
        service = SignerService(store, settings.relay_list, settings.activity_log_size, **kwargs)
        await service.startup()
        app.state.signer_service = service
        yield
        await service.shutdown()

    app = FastAPI(title="NIP-46 Remote Signer", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    # UI (plain HTML + jQuery) served from the same origin as the API: no CORS needed.
    # Mounted last so /api routes take precedence.
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
