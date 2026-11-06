# Inventario de suministros

API FastAPI y agente de terminal para el stock de una tienda de suministros de cafetería. El agente recibe una frase, pide a un modelo que elija una tool y llama al endpoint correspondiente. Cada paso queda en `conversation_log.csv`. Los productos viven en `products.csv`.

El enunciado es el proyecto 4Geeks *AI basic Inventory Agent Loop*. Este README explica cómo arrancar el sistema que hay en el repositorio.

## Arrancar

Hacen falta dos terminales. La API tiene que estar en marcha antes que el agente.

```bash
uv sync --extra dev
```

Terminal 1:

```bash
uv run uvicorn api.app:app --reload
```

Terminal 2, con `GROQ_API_KEY` en el entorno o en un `.env` local (copia `.env.example`):

```bash
uv run python agent.py
```

Sin uv, desde la raíz del repositorio:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn api.app:app --reload
python agent.py
```

El modo por defecto es live: el SDK `openai` apunta a `https://api.groq.com/openai/v1` y la clave se lee de `GROQ_API_KEY`. La clave no se imprime. Si no está definida, el proceso termina y explica cómo seguir. No cambia a mock por su cuenta.

Demo determinista, sin llamada a un modelo:

```bash
uv run python agent.py --mock
```

Esa demo está rotulada `Modo: MOCK`. La regla local elige las tools. No demuestra que el modelo las seleccione.

## Parar y volver a abrir

En la terminal del agente, escribe `salir` o pulsa Ctrl+C. Después para la API con Ctrl+C. `conversation_log.csv` se escribe en cada evento, así que una parada a medias no borra las filas ya guardadas.

Para seguir, arranca otra vez `python agent.py` (o `uv run python agent.py`). La API puede seguir en marcha. El agente abre una sesión nueva en memoria y añade filas al mismo CSV. No lo reescribe.

## Qué se puede decir

Comandos locales, en live y en mock. No pasan por el modelo:

| Comando | Efecto |
| --- | --- |
| `ayuda` | Muestra los comandos y ejemplos. |
| `alertas` | Llama a `GET /inventory/alerts` y muestra un resumen legible. |
| `salir` | Cierra la sesión. |

Frases de ejemplo, con el catálogo que viene en `products.csv`:

```text
Acaban de llegar 30 unidades de leche de avena
Vendimos 12 bolsas de café arábica
¿Qué productos están por agotarse?
Registra 15 cajas de tapas y dime las alertas
lista el inventario
```

En mock solo esas formas están reconocidas. Cualquier otra frase recibe un aviso y no llama a la API. En live el texto se envía al modelo con las cuatro tools.

La transcripción de una pasada mock, generada con el catálogo de ejemplo, está en `docs/demo-mock-transcript.txt`. La primera línea de contenido dice `Modo: MOCK`.

## API

No hay interfaz web. `/docs` y `/redoc` están apagados. El contrato es JSON. `GET /openapi.json` describe los mismos endpoints.

| Método | Ruta | Cuerpo o query | Respuesta |
| --- | --- | --- | --- |
| `GET` | `/inventory` | — | Lista completa. |
| `POST` | `/inventory` | `name`, `quantity`, `unit` | `201` y el producto. `409` si el nombre ya existe. |
| `PATCH` | `/inventory/{product_id}` | `delta` | Suma el delta. Positivo entra, negativo sale. `404` si el id no existe. `400` si el delta es 0 o el stock quedaría por debajo de cero. |
| `GET` | `/inventory/alerts` | `threshold` opcional, por defecto `10` | Productos con cantidad estrictamente menor que el umbral, más un `summary` legible. |

Un dato que no supera la validación responde `422` con `detail` en una frase. Una ruta desconocida responde `404` con un mensaje que indica revisar el método y la ruta.

El umbral compara el número de la cantidad. No convierte kg en unidades ni bolsas en litros.

El fichero por defecto es `products.csv` en la raíz. `PRODUCTS_CSV_PATH` cambia la ruta. El proceso no guarda una copia en memoria: al reiniciarlo lee el mismo CSV.

Catálogo inicial: leche de avena, café arábica, azúcar, vasos, leche entera, sirope de vainilla, filtros y chocolate. Las cantidades por debajo de 10 salen en las alertas.

## Agente

`agent.py` contiene el bucle:

1. Observar: guarda el mensaje de la persona en la memoria de la sesión y en el CSV.
2. Pensar: en live llama a `client.chat.completions.create` con el historial y las tools. En mock aplica la regla local.
3. Actuar: si hay tool calls, llama al endpoint que corresponde al nombre.
4. Actualizar: mete el resultado en el historial.
5. Repetir hasta una respuesta sin tool calls, o hasta `MAX_TOOL_ITERATIONS` (por defecto 8).

El historial de la sesión vive en memoria y se pierde al cerrar el proceso. El CSV no.

Tools: `list_inventory`, `add_product`, `update_stock`, `get_low_stock_alerts`. Cada una tiene nombre, descripción y parámetros con tipo.

Variables:

| Variable | Uso |
| --- | --- |
| `GROQ_API_KEY` | Clave de Groq. Solo la lee el agente. |
| `GROQ_MODEL` | Modelo. Por defecto `llama-3.3-70b-versatile`. |
| `INVENTORY_API_URL` | Base de la API. Por defecto `http://127.0.0.1:8000`. |
| `MAX_TOOL_ITERATIONS` | Tope de vueltas que todavía piden tools. |
| `CONVERSATION_LOG_PATH` | Ruta del registro. Por defecto `conversation_log.csv`. |
| `PRODUCTS_CSV_PATH` | Ruta del inventario. La usa la API. |

## Registro

`conversation_log.csv` tiene las columnas `actor`, `message`, `tool_call`, `timestamp`.

| `actor` | Cuándo |
| --- | --- |
| `user` | Mensaje escrito en la terminal. |
| `agent` | Respuesta final, o la decisión de llamar a una tool (`tool_call` lleva el nombre y `message` los argumentos). |
| `tool` | Resultado devuelto por la API. |

`tool_call` va vacío cuando el evento no es una tool. `timestamp` es ISO 8601 con zona UTC. El fichero solo se abre en append. El mensaje de sistema que configura al modelo no se registra: no es un evento de la conversación.

## Tests

```bash
uv sync --extra dev
uv run pytest
```

Los tests no llaman a Groq. Cubren los endpoints, el reinicio del proceso, el bucle con una función de pensamiento inyectada, el límite de iteraciones, el CSV append-only y la demo mock. Una función inyectada demuestra el cableado del bucle. No sustituye una selección hecha por el modelo.

## Estructura

```text
api/app.py            FastAPI y products.csv
agent.py              Bucle, CLI, modo mock y cliente Groq
alert_format.py       Resumen legible de alertas
safe_csv.py           Bloqueo, append y reemplazo atómico
products.csv          Catálogo inicial
conversation_log.csv  Cabecera del registro
docs/demo-mock-transcript.txt
third_party/python-hello/   Copia del boilerplate de origen
```

## Procedencia del boilerplate

El enunciado indica https://github.com/4GeeksAcademy/python-hello. Ese repositorio no es una plantilla de GitHub (`is_template` es false). La copia sin modificar está en `third_party/python-hello/`, con el commit `142f2a913162efafce897da8bf241fe690f60395` y los SHA-256 en `PROVENANCE.md`. En ese commit no hay fichero `LICENSE`.

El runtime no usa el `server.py` de Flask ni el `main.py` de ejemplo. El enunciado pide `uvicorn api.app:app` y `python agent.py`.

## Límites

- Sin `GROQ_API_KEY` no hay evidencia de una llamada real ni de que el modelo elija las tools. El mock no cubre ese punto.
- El stock es una sola cifra por producto. El relato de la tienda menciona dos locales; este contrato no reparte el stock entre locales.
- El umbral no convierte unidades.
- El modo mock entiende un puñado de frases en español e inglés. El resto del lenguaje natural queda para el modo live.
- No hay UI. El lockup visual no aplica. La jerarquía está en este README, en el texto de la terminal y en los mensajes de error de la API. El detalle está en `auditoria/DESIGN-QA.md`.

## SIGNAL

Perfil académico, sin UI. Texto concreto, estados de error con el siguiente paso (`uvicorn` parado, clave ausente, delta inválido, stock que quedaría negativo) y sin una marca en el pie porque no hay pantalla.
