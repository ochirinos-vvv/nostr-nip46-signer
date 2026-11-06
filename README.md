# Firmante NIP-46 para Stacker News

Aplicación mínima en Python que permite crear o importar una clave secreta de Nostr, guardarla cifrada
y usarla a través de un **firmante remoto NIP-46 ("bunker") implementado en este repositorio** para
iniciar sesión en [Stacker News](https://stacker.news).

```
 Navegador (UI)  ──AJAX──▶  FastAPI  ──▶  Firmante NIP-46  ◀──relays Nostr (kind 24133)──▶  Stacker News
                                          (custodia la clave)
```

La clave privada nunca sale del servicio: Stacker News solo recibe la clave pública y los eventos firmados.

**Estado:** el login en Stacker News con una URI `bunker://` generada por esta aplicación fue verificado
de punta a punta. Los requerimientos detallados, el estado de cada criterio de aceptación y los cambios
respecto al planteamiento inicial están en [REQUERIMIENTO_INICIAL_AI.md](REQUERIMIENTO_INICIAL_AI.md).

## Instalación y ejecución

Requisitos: Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    ·    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # y define SIGNER_PASSPHRASE con un valor propio
python main.py
```

Abrir **http://127.0.0.1:8000/** (UI) o **http://127.0.0.1:8000/docs** (API interactiva).

Para desarrollo con recarga automática: `uvicorn app.main:create_app --factory --reload`.

### Con Docker

```bash
cp .env.example .env        # y define SIGNER_PASSPHRASE
docker compose up -d --build
```

Queda disponible en las mismas URLs. El puerto se publica solo en `127.0.0.1`, ya que la app no tiene
autenticación propia. Las claves cifradas se guardan en el volumen `signer-data` (independiente de la
carpeta `data/` de la ejecución local) y se mantienen entre reinicios; `docker compose down -v` las
elimina. Logs: `docker compose logs -f`.

Variables (`.env`):

| Variable | Descripción |
|---|---|
| `SIGNER_PASSPHRASE` | **Obligatoria.** Cifra las claves guardadas en disco. Si cambia, las claves existentes no se pueden leer. |
| `SIGNER_RELAYS` | Relays donde escucha el firmante, separados por coma. Por defecto `wss://nos.lol,wss://relay.primal.net`. |
| `SIGNER_DATA_DIR` | Carpeta de `keys.json`. Por defecto `data/`. |

> Si `pip` falla por certificados (proxy corporativo con inspección TLS), usar
> `pip install --use-feature=truststore -r requirements.txt`. La app usa el almacén de certificados
> del sistema operativo para conectarse a los relays por la misma razón.

## Demostración del flujo

1. En la UI, **Crear nueva** clave (o **Importar existente** con un `nsec1...`).
2. Con la clave seleccionada, **Generar URI bunker** y copiarla.
3. Abrir el [login de Stacker News con Nostr](https://stacker.news/signup?callbackUrl=https%3A%2F%2Fstacker.news%2F&type=nostr)
   y pegar la URI en la opción de firmante remoto (bunker).
4. En la tabla **Actividad** se ven llegar `connect` → `get_public_key` → `sign_event`, y Stacker News
   inicia la sesión con la identidad de esa clave.

También se soporta el flujo inverso: si el sitio muestra una URI `nostrconnect://`, se pega en la UI y el
firmante inicia la conexión. Este flujo tiene pruebas automatizadas, pero no se verificó contra Stacker News.

### Cómo funciona NIP-46 aquí

1. Cada clave guardada tiene un firmante suscrito en los relays a los eventos kind 24133 dirigidos a
   su clave pública.
2. La URI `bunker://<pubkey>?relay=...&secret=...` lleva un secreto de un solo uso.
3. Stacker News envía `connect` con ese secreto; el firmante autoriza a ese cliente (identificado por
   su clave pública) y responde `ack`.
4. Luego llegan `get_public_key` y `sign_event`; el firmante firma con la clave custodiada y responde
   por los mismos relays. Cada mensaje va cifrado entre cliente y firmante (NIP-44).

## API

Prefijo `/api`; `{pubkey}` acepta hex o `npub`. Ningún endpoint devuelve la clave secreta.

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/health` | Estado del backend |
| POST | `/keys` | Generar (sin `secret`) o importar (`secret`: `nsec1...` o hex) una clave |
| GET | `/keys` | Listar claves (solo datos públicos) |
| DELETE | `/keys/{pubkey}` | Eliminar una clave y detener su firmante |
| POST | `/keys/{pubkey}/bunker` | Generar una URI `bunker://` de un solo uso |
| POST | `/keys/{pubkey}/nostrconnect` | Aceptar una URI `nostrconnect://` |
| GET | `/keys/{pubkey}/status` | Relays conectados y clientes autorizados |
| GET | `/keys/{pubkey}/activity` | Historial de solicitudes NIP-46 |
| DELETE | `/keys/{pubkey}/clients/{client_pubkey}` | Revocar un cliente |

Los errores siguen el formato de FastAPI (`{"detail": "..."}`) con códigos 404, 409 y 422.

## Alcance y supuestos

El enunciado deja varias cosas abiertas; estas son las decisiones tomadas:

- **"Implementado por la persona postulante"** se interpretó como: el protocolo NIP-46 y el cifrado
  NIP-44 se implementan aquí, sin usar un SDK de Nostr que ya los resuelva. Solo se usan librerías de
  bajo nivel: `coincurve` (secp256k1/Schnorr) y `cryptography` (ChaCha20, AES, Fernet, scrypt).
  NIP-44 se valida con el vector de prueba oficial de la especificación.
- **Un solo usuario, uso local.** El servicio corre en `127.0.0.1` y no tiene login propio:
  quien accede a la UI controla las claves. Se pueden guardar varias claves; cada una tiene su firmante.
- **Aprobación automática.** Un cliente que se conecta con el secreto de un solo uso del `bunker://`
  queda autorizado y todas sus solicitudes se firman sin confirmación manual. Se puede revocar desde la UI.
- **La clave del usuario es también la clave de transporte NIP-46.** NIP-46 permite separarlas;
  usar la misma simplifica el flujo sin cambiar lo que ve Stacker News.
- **Cifrado de transporte:** NIP-44 por defecto, con respaldo en NIP-04 para clientes antiguos
  (se responde con el mismo esquema que usó el cliente).
- **Métodos soportados:** `connect`, `get_public_key`, `sign_event`, `ping`, `nip04_encrypt/decrypt`,
  `nip44_encrypt/decrypt` y `get_relays`.
- **UI:** HTML, CSS y JavaScript con jQuery (librería de utilidades, no un framework de frontend),
  incluido en el repositorio y servido por la misma app, por lo que no requiere CORS ni build.

## Tradeoffs

| Decisión | A favor | En contra |
|---|---|---|
| Claves cifradas en un JSON (Fernet + scrypt sobre una passphrase) | Simple, sin base de datos, la clave no queda en texto plano | La passphrase vive en `.env` en la misma máquina; no hay HSM ni keychain del SO |
| La API nunca devuelve la clave secreta | Coherente con el modelo de firmante remoto | Una clave generada aquí no se puede exportar como respaldo desde la UI |
| Sesiones de clientes en memoria | Menos estado que gestionar | Al reiniciar hay que volver a conectar desde Stacker News |
| Aprobación automática | El flujo de demo es directo | Un cliente autorizado puede pedir firmar cualquier evento |
| Relays públicos fijos por configuración | Sin infraestructura propia | Dependemos de su disponibilidad (`relay.nsec.app` y `relay.damus.io` fallaron desde la red de desarrollo, por eso no son los valores por defecto) |
| Implementación propia de NIP-44/NIP-46 | Cumple el enunciado y se entiende el protocolo | Más código que mantener que con un SDK; mitigado con tests y el vector oficial |

Fuera de alcance: aprobación de solicitudes por permiso/tipo de evento, persistencia de sesiones,
multiusuario con autenticación, y despliegue público.

## Limitaciones conocidas

- **No apto para producción.** La custodia de claves es una simplificación para la prueba.
- Sin autenticación propia: cualquiera con acceso a `127.0.0.1:8000` controla las claves.
- Las solicitudes de un cliente autorizado se firman sin confirmación.
- Al reiniciar se pierden las sesiones de clientes y el historial de actividad; hay que volver a
  conectar desde Stacker News con una nueva URI `bunker://`.
- Depende de relays públicos de terceros.
- El flujo `nostrconnect://` no se probó contra Stacker News.

## Evidencia de funcionamiento

- **Pruebas automatizadas:** 23 pruebas que pasan (ver sección Tests).
- **Relays reales:** prueba manual en la que el firmante y un cliente NIP-46 simulado se comunicaron a
  través de `relay.primal.net` (`connect` → `get_public_key` → `sign_event` con firma válida).
- **Stacker News:** inicio de sesión completado con una URI `bunker://` generada por la API; la tabla
  de actividad de la UI muestra las solicitudes recibidas durante el login.

## Estructura

```
app/
  nostr/      primitivas del protocolo: claves (NIP-19), eventos (NIP-01), NIP-44, NIP-04, cliente de relays (NIP-42)
  signer/     firmante NIP-46: transporte por relays + despacho de métodos (sin I/O, testeable)
  storage/    almacén de claves cifrado
  api/        rutas FastAPI bajo /api
  static/     UI (HTML + CSS + jQuery)
  services.py une el almacén con un firmante en ejecución por clave
tests/        criptografía, flujo NIP-46 completo con un cliente simulado, API
```

## Tests

```bash
python -m pytest
```

Son 23 pruebas y no requieren red: los relays se reemplazan por un pool en memoria. Cubren el vector oficial de NIP-44,
el flujo `bunker://` y `nostrconnect://` completo (con NIP-44 y NIP-04), rechazo de clientes no
autorizados y secretos reutilizados, y el cifrado de las claves en disco.

## Registros de conversación con el agente de IA

El desarrollo se hizo con **Claude Code**. Los registros de la conversación están en
[`ai-logs/`](ai-logs/).
