import pytest
from pydantic import SecretStr

from app.config import Settings


class FakePool:
    """In-memory stand-in for RelayPool: records published events, delivers injected ones."""

    instances: list["FakePool"] = []

    def __init__(self, urls, keys, on_event):
        self.urls = list(urls)
        self.on_event = on_event
        self.published: list[dict] = []
        self.subs: dict[str, dict] = {}
        FakePool.instances.append(self)

    def start(self):
        pass

    async def stop(self):
        pass

    async def subscribe(self, sub_id, filter_):
        self.subs[sub_id] = filter_

    async def publish(self, event):
        self.published.append(event)

    async def add_relays(self, urls):
        self.urls += [u for u in urls if u not in self.urls]

    def status(self):
        return {u: True for u in self.urls}


@pytest.fixture
def fake_pool():
    FakePool.instances.clear()
    return FakePool


@pytest.fixture
def settings(tmp_path):
    return Settings(passphrase=SecretStr("test-passphrase"), data_dir=tmp_path,
                    relays="wss://relay.example")
