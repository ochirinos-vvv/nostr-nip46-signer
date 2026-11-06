# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose and spec

Technical test (delivered to a Chilean government hiring process, so README/UI copy is in Spanish): a
minimal Nostr NIP-46 remote signer ("bunker") whose key is used to log into Stacker News. The
end-to-end Stacker News login via a `bunker://` URI has been verified manually and works.

`REQUERIMIENTO_INICIAL_AI.md` is the detailed spec (v1.1, rewritten to match what was built; its
section 14 lists every change vs. the original v1.0 and why). Keep it, the README and the code in sync.
Hard constraints:
- Backend Python 3.11 + FastAPI only. Frontend HTML/CSS/JS + jQuery only (no React/Vue/Angular, no
  TypeScript, no Node server, no heavy CSS framework), consuming the backend exclusively via AJAX,
  served from the same origin.
- Never return the secret key from any endpoint, never log it, never store it in the browser.
- Low-level crypto comes from `coincurve`/`cryptography`; only the Nostr protocols (NIP-01/04/44/46)
  are implemented here, because the test requires a self-built signer.
- Keep business logic out of the endpoints; no features beyond scope; main flow before extras.
- Deliverables include the Claude Code conversation logs in `ai-logs/` (not created yet; must be
  checked for secrets before publishing).

## Commands (Windows, venv in `.venv`)

```powershell
.\.venv\Scripts\python.exe -m pip install --use-feature=truststore -r requirements.txt  # truststore: corporate TLS proxy
.\.venv\Scripts\python.exe main.py                     # UI at http://127.0.0.1:8000/, Swagger at /docs
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload           # dev with reload
.\.venv\Scripts\python.exe -m pytest                   # all tests (no network needed)
.\.venv\Scripts\python.exe -m pytest tests/test_remote_signer.py::test_bunker_login_flow
```

Docker: `docker compose up -d --build` (same URLs). The image runs uvicorn directly on `0.0.0.0`
because `main.py` binds to `127.0.0.1`; compose publishes only on `127.0.0.1:8000`, reads `.env`, and
keeps keys in the `signer-data` volume (separate from the local `data/`). `.dockerignore` excludes
`tests/`, so tests run only from the venv.

`SIGNER_PASSPHRASE` is required (in `.env` or the environment, see `.env.example`); changing it makes
existing `data/keys.json` unreadable. No linter/formatter is configured.

## Architecture

- `app/nostr/` — protocol primitives, no app logic: `keys.py` (KeyPair, nsec/npub, unhashed ECDH
  `shared_x`), `event.py` (NIP-01 id + Schnorr sign/verify via `coincurve`), `nip44.py`, `nip04.py`
  (legacy fallback), `relay.py` (`RelayClient` with reconnect + NIP-42 AUTH, `RelayPool` fan-out
  with event dedup and dynamic `add_relays`). TLS uses `truststore` (OS cert store).
- `app/signer/remote_signer.py` — `RemoteSigner`, one per stored key, using the user's key as the
  NIP-46 transport key. `_on_event` decrypts kind 24133 events (NIP-44, or NIP-04 if the payload
  contains `?iv=`) and replies with the same scheme. `handle_request` is the I/O-free JSON-RPC
  dispatcher. Clients get authorized by a single-use secret from `new_bunker_uri()` or by
  `accept_nostrconnect(uri)`; authorized clients are auto-approved; sessions are in memory only.
- `app/storage/key_store.py` — Fernet with a scrypt-derived key from the passphrase (salt in the file).
- `app/services.py` — `SignerService`: key store + dict of running signers, starts one per stored key
  at startup. Pubkeys accepted as hex or npub (`normalize_pubkey`).
- `app/api/` — routes under `/api`: `/keys`, `/keys/{pubkey}`, `/keys/{pubkey}/bunker|nostrconnect|status|activity`,
  `/keys/{pubkey}/clients/{client}`.
- `app/static/` — UI: jQuery vendored in `static/vendor/`, polls status/activity every 3 s. Render
  user data with `.text()`; read hex ids with `.attr()` (not `.data()`, which may coerce to numbers).
- `app/main.py` — `create_app(settings, pool_factory)`; the lifespan builds the service. Static files
  are mounted at `/` after the router so `/api/*` wins. Tests inject `tests/conftest.py::FakePool`
  as `pool_factory` to avoid real relays.

## Notes

- From this network `relay.nsec.app` times out and `relay.damus.io` returns 503; defaults are
  `nos.lol` and `relay.primal.net`.
- The repo is not yet under git; `.gitignore` excludes `.env`, `data/`, `.venv/`.
