from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SIGNER_", extra="ignore")

    # Encrypts the secret keys at rest. Required: the app refuses to start without it.
    passphrase: SecretStr
    data_dir: Path = Path("data")
    # Comma-separated relays where the signer listens for NIP-46 requests.
    relays: str = "wss://nos.lol,wss://relay.primal.net"
    activity_log_size: int = 200

    @property
    def relay_list(self) -> list[str]:
        return [r.strip() for r in self.relays.split(",") if r.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
