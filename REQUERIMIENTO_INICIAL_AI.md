# Requerimientos Técnicos
## Aplicación de firma remota Nostr mediante NIP-46 e inicio de sesión en Stacker News

**Versión:** 1.1 (ajustada a lo implementado; los cambios respecto a la 1.0 están en la sección 14)
**Lenguaje Backend:** Python 3.11
**Framework Backend:** FastAPI
**Frontend:** HTML5, CSS3, JavaScript y jQuery
**Comunicación:** AJAX mediante HTTP/JSON
**Agente de desarrollo:** Claude Code

---

# 1. Objetivo del proyecto

Desarrollar una aplicación web mínima que permita a un usuario ingresar o generar una clave secreta de
Nostr y utilizarla mediante un firmante remoto implementado con el protocolo NIP-46 (Nostr Remote
Signing) para iniciar sesión en Stacker News.

El desarrollo se realizó en dos etapas:

1. **Backend:** primitivas Nostr, firmante NIP-46, almacenamiento de claves y endpoints REST con
   Python 3.11 y FastAPI.
2. **Frontend:** interfaz web con HTML, CSS, JavaScript y jQuery, que consume el backend mediante AJAX.

El objetivo es una solución funcional, pequeña, comprensible y fácil de ejecutar localmente.

# 2. Alcance funcional

La aplicación implementa:

1. Importar una clave secreta de Nostr existente (`nsec1...` o hexadecimal).
2. Generar una nueva clave secreta de Nostr.
3. Obtener la clave pública (hex y `npub`) correspondiente.
4. Un firmante remoto NIP-46 ("bunker") por cada clave guardada.
5. Conexión entre un cliente NIP-46 y el firmante, en ambos sentidos: `bunker://` (la inicia el
   firmante) y `nostrconnect://` (la inicia el cliente).
6. Procesamiento de solicitudes NIP-46 recibidas a través de relays Nostr.
7. Firma de eventos Nostr con la clave custodiada por el backend.
8. Inicio de sesión en Stacker News usando el firmante.
9. Visualización del estado de los relays, los clientes autorizados y la actividad del firmante.

**Fuera de alcance:**

- Billetera de criptomonedas.
- Extensión de navegador.
- Firmante universal.
- Aprobación manual de cada solicitud o permisos por tipo de evento.
- Persistencia de las sesiones de clientes NIP-46.
- Autenticación de usuarios de la propia aplicación (uso local, un solo usuario).
- Custodia de claves apta para producción (HSM, keychain del sistema operativo).
- Infraestructura propia de relays Nostr.

# 3. Arquitectura tecnológica

## 3.1. Backend

| Tecnología | Uso |
|---|---|
| Python 3.11 | Lenguaje |
| FastAPI | API REST y servicio de los archivos estáticos de la UI |
| Uvicorn | Servidor ASGI |
| Pydantic / pydantic-settings | Validación de datos y configuración desde `.env` |
| websockets | Conexión persistente con los relays Nostr |
| coincurve | secp256k1: derivación de claves, firma y verificación Schnorr (BIP-340), ECDH |
| cryptography | ChaCha20, AES-CBC, HMAC, Fernet y scrypt |
| bech32 | Codificación `nsec` / `npub` (NIP-19) |
| truststore | Uso del almacén de certificados del sistema operativo (red con proxy TLS corporativo) |
| pytest, pytest-asyncio, HTTPX | Pruebas (HTTPX solo a través del `TestClient` de FastAPI) |

No se utilizó un SDK de Nostr que ya incluya NIP-46, porque el enunciado de la prueba exige que el
firmante NIP-46 sea implementado por la persona postulante. Las operaciones criptográficas de bajo
nivel se delegan en `coincurve` y `cryptography`; sobre ellas se implementan NIP-01, NIP-04, NIP-44 y
NIP-46 (ver sección 7).

## 3.2. Frontend

- HTML5, CSS3, JavaScript y jQuery 3.7.1 (incluido en el repositorio, sin CDN ni paso de build).
- Sin React, Angular, Vue, TypeScript, Node.js ni frameworks CSS.
- Consume exclusivamente los endpoints REST del backend mediante `$.ajax`.
- Se sirve desde el mismo origen que la API, por lo que no requiere CORS.

## 3.3. Comunicación

- Navegador ↔ backend: HTTP + JSON.
- Backend ↔ clientes NIP-46 (Stacker News): eventos Nostr kind 24133 publicados en relays públicos
  mediante WebSocket, con contenido cifrado.

```text
 Navegador (UI)  ──AJAX──▶  FastAPI  ──▶  Firmante NIP-46  ◀──relays Nostr (kind 24133)──▶  Stacker News
                                          (custodia la clave)
```

# 4. Etapa 1: Backend

## 4.1. Estructura del proyecto

```text
gob-digital-test/
├── main.py                    # arranque: uvicorn con la fábrica create_app
├── app/
│   ├── main.py                # create_app(): ciclo de vida, router y archivos estáticos
│   ├── config.py              # configuración (pydantic-settings, prefijo SIGNER_)
│   ├── services.py            # SignerService: almacén de claves + un firmante por clave
│   ├── api/
│   │   ├── routes.py          # endpoints REST bajo /api
│   │   └── schemas.py         # modelos de request/response
│   ├── nostr/                 # primitivas del protocolo, sin lógica de aplicación
│   │   ├── keys.py            # claves, nsec/npub (NIP-19), ECDH
│   │   ├── event.py           # id y firma de eventos (NIP-01)
│   │   ├── nip44.py           # cifrado NIP-44 v2
│   │   ├── nip04.py           # cifrado NIP-04 (compatibilidad)
│   │   └── relay.py           # cliente de relays: reconexión, deduplicación, AUTH NIP-42
│   ├── signer/
│   │   └── remote_signer.py   # firmante NIP-46
│   ├── storage/
│   │   └── key_store.py       # almacén de claves cifrado
│   └── static/                # frontend
│       ├── index.html
│       ├── app.css
│       ├── app.js
│       └── vendor/jquery-3.7.1.min.js
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

Se simplificó la estructura propuesta en la versión 1.0 (`backend/` y `frontend/` separados, varias
capas de servicios), manteniendo la separación entre primitivas del protocolo, firmante, almacenamiento,
servicio de aplicación, API y frontend.

## 4.2. Gestión de claves

### RF-001: Generar clave secreta

El sistema genera una clave secreta secp256k1 válida (32 bytes aleatorios, validados como escalar de
la curva) y obtiene su clave pública. La clave secreta **no se devuelve** al cliente HTTP: la
respuesta incluye solo la clave pública en hex, el `npub`, el nombre y la fecha de creación.

### RF-002: Ingresar clave secreta

El sistema acepta una clave existente en formato `nsec1...` o en 64 caracteres hexadecimales:

1. Valida el formato (bech32 con prefijo `nsec`, o hexadecimal de 32 bytes).
2. Comprueba que sea una clave privada válida de la curva.
3. Obtiene su clave pública.
4. La guarda y pone en marcha su firmante.

Una clave ya guardada no se puede importar dos veces (409).

### RF-003: Custodia de claves

Las claves se guardan **cifradas en disco** en `data/keys.json`:

- Cifrado con Fernet, usando una llave derivada con scrypt de la passphrase `SIGNER_PASSPHRASE`
  (definida en `.env`); la sal se guarda en el mismo archivo.
- Si la passphrase no coincide con las claves guardadas, la aplicación no inicia.
- Ningún endpoint devuelve la clave secreta.
- Las claves no se escriben en logs.
- Se puede eliminar una clave (`DELETE /api/keys/{pubkey}`), lo que también detiene su firmante.

Esta custodia es una simplificación para la prueba y no una implementación de seguridad productiva:
la passphrase reside en la misma máquina que el archivo cifrado.

## 4.3. Primitivas Nostr

### RF-004: Obtener clave pública

La clave pública x-only de 32 bytes (BIP-340) se deriva de la clave secreta y se expone en hex y como
`npub` (NIP-19).

### RF-005: Construir eventos Nostr

Los eventos tienen los campos `id`, `pubkey`, `created_at`, `kind`, `tags`, `content` y `sig`. El `id`
es el SHA-256 de la serialización canónica `[0, pubkey, created_at, kind, tags, content]` (NIP-01).

### RF-006: Firmar eventos

La firma es Schnorr BIP-340 sobre el `id`, con aleatoriedad auxiliar. También se verifica la firma de
los eventos recibidos desde los relays; los inválidos se descartan.

La firma no se expone como endpoint REST independiente: solo se realiza a través del firmante NIP-46
(ver RF-010).

## 4.4. Firmante NIP-46

### RF-007: Firmante remoto NIP-46

Cada clave guardada tiene un firmante en ejecución, suscrito en los relays configurados a los eventos
kind 24133 dirigidos a su clave pública (tag `p`). La clave del usuario se usa también como clave de
transporte NIP-46 (la especificación permite separarlas).

### RF-008: Establecer conexión NIP-46

Se implementan los dos mecanismos de conexión de NIP-46:

- **`bunker://` (lo inicia el firmante):** el usuario genera una URI
  `bunker://<pubkey-firmante>?relay=...&secret=...` y la pega en el cliente. El cliente envía
  `connect` con el `secret`; si es válido, el firmante autoriza al cliente y responde `ack`. **Cada
  secreto sirve una sola vez.**
- **`nostrconnect://` (lo inicia el cliente):** el usuario pega en la UI la URI que muestra el cliente.
  El firmante se conecta a los relays indicados, autoriza al cliente y le envía la respuesta `connect`
  con el `secret` de la URI.

La sesión se identifica por la clave pública del cliente. Los clientes autorizados se mantienen en
memoria (se pierden al reiniciar) y se pueden revocar.

El cifrado de transporte es NIP-44 v2; si el cliente envía contenido NIP-04 (contiene `?iv=`), el
firmante responde con NIP-04.

### RF-009: Procesar solicitudes NIP-46

Métodos implementados: `connect`, `get_public_key`, `sign_event`, `ping`, `nip04_encrypt`,
`nip04_decrypt`, `nip44_encrypt`, `nip44_decrypt` y `get_relays`.

Manejo de errores:

- Un cliente no autorizado que envía cualquier método distinto de `connect` recibe el error
  `unauthorized`.
- Un `connect` con secreto inválido o ya usado recibe un error.
- Un método desconocido recibe el error `unsupported method`.
- Los mensajes que no se pueden descifrar o interpretar se descartan y se registran en el log.

Cada solicitud queda registrada en un historial de actividad en memoria (últimas 200).

### RF-010: Firmar remotamente

Cuando un cliente autorizado envía `sign_event`:

1. El firmante recibe el evento kind 24133 y verifica su firma.
2. Descifra la solicitud y comprueba que el cliente esté autorizado.
3. Usa la clave asociada al firmante que recibió la solicitud.
4. Firma el evento (completa `pubkey`, `id` y `sig`).
5. Cifra la respuesta con el mismo esquema que usó el cliente.
6. La publica en los relays dirigida al cliente.

Las solicitudes de clientes autorizados se aprueban automáticamente. La clave privada nunca se envía
al cliente.

### RF-011: Configuración de relays

Los relays se configuran en `.env` con `SIGNER_RELAYS` (separados por coma), fuera de la lógica de
negocio. Por defecto: `wss://nos.lol` y `wss://relay.primal.net`. El cliente de relays reconecta
automáticamente y responde a desafíos de autenticación NIP-42.

## 4.5. API REST

Prefijo: `/api`.

| Método | Endpoint | Descripción |
|---|---|---|
| GET | `/health` | Estado del backend |
| POST | `/keys` | Generar (sin `secret`) o importar (con `secret`) una clave |
| GET | `/keys` | Listar las claves guardadas (solo datos públicos) |
| DELETE | `/keys/{pubkey}` | Eliminar una clave y detener su firmante |
| POST | `/keys/{pubkey}/bunker` | Generar una URI `bunker://` de un solo uso |
| POST | `/keys/{pubkey}/nostrconnect` | Aceptar una URI `nostrconnect://` |
| GET | `/keys/{pubkey}/status` | Estado de los relays y clientes autorizados |
| GET | `/keys/{pubkey}/activity` | Historial de solicitudes NIP-46 |
| DELETE | `/keys/{pubkey}/clients/{client_pubkey}` | Revocar un cliente |

`{pubkey}` acepta hex o `npub`. Ningún endpoint entrega la clave secreta.

## 4.6. Contratos de API

Las respuestas exitosas devuelven directamente el recurso (modelos Pydantic), por ejemplo:

```json
{
    "pubkey": "49e401c6...",
    "npub": "npub1f8jq...",
    "name": "orlando",
    "created_at": 1793881496
}
```

Los errores usan el formato estándar de FastAPI:

```json
{
    "detail": "Secret key must be 32 bytes"
}
```

Códigos HTTP utilizados:

- 200: operación exitosa.
- 201: clave creada.
- 204: clave eliminada o cliente revocado.
- 404: clave o cliente inexistente.
- 409: la clave ya está guardada.
- 422: datos inválidos (clave secreta, pubkey o URI `nostrconnect://` mal formadas).
- 500: error interno.

## 4.7. Documentación automática

Swagger UI disponible en `/docs`. El backend se puede probar completo sin el frontend.

## 4.8. Pruebas del backend

23 pruebas automatizadas (`python -m pytest`), sin acceso a red (los relays se reemplazan por un
pool en memoria):

- Generación, importación y validación de claves; codificación `nsec`/`npub`.
- Vector de prueba oficial de NIP-44, cifrado simétrico, rechazo de contenido alterado y NIP-04.
- Construcción, firma y verificación de eventos.
- Flujo NIP-46 completo `bunker://` (`connect` → `get_public_key` → `sign_event`) con NIP-44 y NIP-04,
  simulando el cliente.
- Flujo `nostrconnect://`.
- Rechazo de clientes no autorizados, secretos reutilizados o incorrectos, y eventos dirigidos a otro
  firmante.
- Endpoints de la API, servicio de la UI y cifrado de las claves en disco.

Además, se ejecutó una prueba manual con relays reales (firmante y cliente simulado comunicándose a
través de `relay.primal.net`) y se probaron los endpoints con Swagger y `curl`.

# 5. Etapa 2: Frontend

## 5.1. Diseño de interfaz

Página única en dos columnas (una columna en pantallas angostas), con modo oscuro automático.

### Sección 1: Tu clave

- Pestañas **Crear nueva** e **Importar existente**.
- El campo de clave secreta es de tipo contraseña.
- Lista de claves guardadas con nombre y `npub`; un clic selecciona la clave.
- Copiar el `npub` y eliminar la clave (con confirmación).
- La clave no se guarda en LocalStorage, SessionStorage ni cookies.

### Sección 2: Conectar con Stacker News

- Instrucciones en tres pasos.
- Botón **Generar URI bunker**, con botón para copiarla.
- Enlace al login de Stacker News con Nostr.
- Sección desplegable para pegar una URI `nostrconnect://`.

### Sección 3: Estado

- Relays con indicador de conexión.
- Clientes autorizados, con nombre o clave pública, mecanismo de conexión, última actividad y botón
  **Revocar**.
- Tabla de actividad (hora, método, cliente, resultado y detalle, por ejemplo el kind firmado). Se
  actualiza cada 3 segundos y permite ver en vivo las solicitudes `connect`, `get_public_key` y
  `sign_event` durante el login.

No hay una sección separada de "prueba de firma": la firma remota se demuestra con el login real en
Stacker News y queda visible en la tabla de actividad.

## 5.2. Comunicación AJAX

Toda la lógica del frontend está en `app/static/app.js`. Las llamadas a la API pasan por una única
función `api(method, path, body)` que envuelve `$.ajax`; el mismo archivo gestiona los eventos de la
interfaz, actualiza el HTML, muestra los mensajes y bloquea los botones durante las operaciones.

## 5.3. Experiencia de usuario

- Botones deshabilitados durante las operaciones en curso.
- Mensajes emergentes de confirmación y de error (con el `detail` que devuelve la API).
- Validación de campos (obligatorios en el navegador; formato de la clave en el backend).
- Estado de conexión de los relays y de los clientes actualizado automáticamente.
- Los datos se muestran como texto (`.text()`), sin interpretar HTML.

# 6. Flujo principal de funcionamiento

1. El usuario abre `http://127.0.0.1:8000/`.
2. Genera una clave nueva o importa una existente.
3. El backend valida la clave, la guarda cifrada y pone en marcha su firmante en los relays.
4. El usuario genera una URI `bunker://`.
5. Abre el login de Stacker News con Nostr y pega la URI en la opción de firmante remoto.
6. Stacker News envía `connect` con el secreto; el firmante lo autoriza.
7. Stacker News pide `get_public_key` y luego `sign_event` del evento de autenticación.
8. El firmante responde por los relays y Stacker News inicia la sesión con esa identidad.
9. La tabla de actividad de la UI muestra cada solicitud y su resultado.

**Integración con Stacker News:** Stacker News soporta NIP-46 directamente en el navegador (acepta una
URI `bunker://`), por lo que no fue necesario un adaptador. El flujo `bunker://` se verificó de punta a
punta con Stacker News. El flujo `nostrconnect://` está implementado y probado con pruebas
automatizadas, pero no se verificó contra Stacker News.

# 7. Seguridad y consideraciones técnicas

1. La clave privada nunca se expone mediante la API.
2. Las claves privadas no se escriben en logs.
3. Las claves privadas no se almacenan en el navegador.
4. Las claves se guardan cifradas en disco con una passphrase (ver RF-003).
5. Se verifican las firmas de los eventos recibidos y se valida que el cliente esté autorizado.
6. Los secretos de conexión `bunker://` son de un solo uso.
7. Los errores criptográficos (MAC inválido, padding, versión desconocida) se manejan sin interrumpir
   el firmante.
8. Las operaciones criptográficas de bajo nivel (curva elíptica, Schnorr, cifrados simétricos, HMAC,
   KDF) se delegan en `coincurve` y `cryptography`. Los esquemas NIP-04 y NIP-44 se componen en el
   proyecto a partir de esas primitivas, porque el enunciado exige implementar el firmante; NIP-44 se
   valida con el vector de prueba oficial de la especificación.
9. Limitaciones conocidas: aprobación automática de las solicitudes de clientes autorizados, sesiones
   en memoria, passphrase en la misma máquina, sin autenticación de la propia aplicación (pensada
   para `127.0.0.1`).
10. La solución no es apta para producción.

Backend y frontend comparten el mismo origen, por lo que no se configura CORS.

# 8. Configuración y ejecución

```bash
python -m venv .venv
.venv\Scripts\activate             # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt    # con proxy TLS corporativo: --use-feature=truststore
cp .env.example .env               # definir SIGNER_PASSPHRASE
python main.py
```

Para desarrollo con recarga automática:

```bash
uvicorn app.main:create_app --factory --reload
```

Con Docker (alternativa; agregado después de la versión 1.0):

```bash
docker compose up -d --build
```

- UI: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`

No se requiere Node.js.

# 9. Entregables

1. Código fuente del backend (`app/`).
2. Código fuente del frontend (`app/static/`).
3. Archivo de dependencias (`requirements.txt`).
4. Archivo `.env.example`.
5. README con instalación, ejecución, arquitectura, supuestos, tradeoffs y limitaciones.
6. Este documento de requerimientos.
7. Registros de conversación con Claude Code (`ai-logs/`).

La arquitectura se documenta en el README y en este documento; no hay un `docs/architecture.md`
separado.

# 10. Criterios de aceptación

| ID | Criterio | Estado |
|---|---|---|
| CA-001 | Generar identidad | Cumplido (pruebas automatizadas y UI) |
| CA-002 | Importar identidad | Cumplido (`nsec` y hex) |
| CA-003 | Obtener clave pública | Cumplido (hex y `npub`) |
| CA-004 | Firmar evento | Cumplido, a través de NIP-46 |
| CA-005 | Conexión NIP-46 | Cumplido (`bunker://` y `nostrconnect://`) |
| CA-006 | Solicitud remota | Cumplido |
| CA-007 | Custodia de claves | Cumplido: la clave no llega al frontend (se guarda cifrada en disco) |
| CA-008 | Comunicación AJAX | Cumplido |
| CA-009 | Interfaz | Cumplido |
| CA-010 | Login Stacker News | Cumplido, verificado manualmente con `bunker://` |
| CA-011 | Documentación | Cumplido (README y este documento) |
| CA-012 | Registros IA | Pendiente de copiar a `ai-logs/` al cierre |

# 11. Estrategia de desarrollo seguida

1. **Backend:** primitivas Nostr, validación de NIP-44 con el vector oficial, firmante NIP-46,
   cliente de relays, almacén de claves, servicio y API, con pruebas automatizadas.
2. **Validación con relays reales:** prueba manual firmante ↔ cliente simulado. Se detectó que
   `relay.nsec.app` (timeout) y `relay.damus.io` (HTTP 503) no respondían desde la red de desarrollo,
   y se cambiaron los relays por defecto.
3. **Validación con Stacker News:** login real con una URI `bunker://` generada por la API.
4. **Frontend:** HTML, CSS y jQuery sobre la API existente.
5. **Documentación:** README y ajuste de este documento a lo implementado.

# 12. Restricciones para el agente de IA

1. Python 3.11 para el backend.
2. FastAPI como framework backend.
3. HTML, CSS, JavaScript y jQuery para el frontend.
4. Sin frameworks adicionales innecesarios.
5. Sin funcionalidades fuera del alcance.
6. Priorizar simplicidad y claridad del código.
7. Lógica de negocio separada de los endpoints.
8. Evitar duplicación de código.
9. Delegar las primitivas criptográficas en bibliotecas probadas; implementar solo los protocolos
   Nostr necesarios para el firmante.
10. Documentar cualquier supuesto técnico.
11. Validar cada etapa antes de avanzar.
12. Priorizar el flujo principal por sobre funcionalidades secundarias.

# 13. Referencias técnicas

- Nostr: https://nostr.com
- NIP-01: https://github.com/nostr-protocol/nips/blob/master/01.md
- NIP-04: https://github.com/nostr-protocol/nips/blob/master/04.md
- NIP-19: https://github.com/nostr-protocol/nips/blob/master/19.md
- NIP-42: https://github.com/nostr-protocol/nips/blob/master/42.md
- NIP-44: https://github.com/nostr-protocol/nips/blob/master/44.md
- NIP-46: https://github.com/nostr-protocol/nips/blob/master/46.md
- Stacker News - Login Nostr: https://stacker.news/signup?callbackUrl=https%3A%2F%2Fstacker.news%2F&type=nostr

# 14. Cambios respecto a la versión 1.0

| Tema | Versión 1.0 | Implementado | Motivo |
|---|---|---|---|
| Custodia de claves | Solo en memoria | Cifrada en disco con passphrase | Evitar reingresar la clave en cada reinicio y que el bunker siga disponible para Stacker News |
| Criptografía | No implementar criptografía | Primitivas de bibliotecas; NIP-04/NIP-44/NIP-46 implementados aquí | El enunciado exige un firmante NIP-46 propio |
| Clave secreta generada | Se devuelve en hex | No se devuelve nunca | Coherencia con el modelo de firmante remoto |
| Identidades | Una identidad activa | Varias claves, cada una con su firmante | Sale natural del diseño; no agrega administración avanzada |
| Prefijo de la API | `/api/v1` | `/api` | Simplicidad; no hay más versiones |
| Formato de respuestas | `{success, message, data}` | Recurso directo; errores `{"detail": ...}` de FastAPI | Usar el estándar del framework |
| Endpoints | `/keys/generate`, `/keys/import`, `/nostr/sign`, `/nip46/connect`… | Recursos por clave (sección 4.5) | Un firmante por clave; la firma solo ocurre vía NIP-46 |
| Firma vía REST | `POST /nostr/sign` | No existe | La firma debe pasar por el firmante remoto, no por la API |
| Estructura | `backend/` y `frontend/`, varias capas de servicios | Un paquete `app/` con la UI en `static/` | Menos archivos, misma separación de responsabilidades |
| Frontend | `api.js` + `app.js`, sección "Prueba de firma", botón de login | Un `app.js` con función `api()` central; actividad en vivo; enlace al login | La demostración real de firma es el login en Stacker News |
| Ejecución | `uvicorn app.main:app --reload` | `python main.py` o `uvicorn app.main:create_app --factory` | La app se crea con una fábrica para poder inyectar dependencias en las pruebas |
| Documento de arquitectura | `docs/architecture.md` | En el README y en este documento | Evitar duplicar documentación |
| Integración con Stacker News | Posible adaptador | No fue necesario | Stacker News acepta `bunker://` directamente |
