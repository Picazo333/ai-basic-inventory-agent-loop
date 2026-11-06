# Rúbrica — AI basic Inventory Agent Loop

Fuente de autoridad: enunciado oficial `content/projects/ai-basic-inventory-agent-loop` (commit del syllabus `fd2da034894ba93ba738559280ccde074ab1d953`), en inglés y en español. Las reglas de fase 2 (mock, Groq sin clave, SIGNAL sin UI) están debajo y no sustituyen al enunciado.

Estado de cada fila: la justificación con PASS, FAIL o BLOCKED está en `RUBRIC_JUSTIFICATION.md`. Esta rúbrica solo fija los criterios, antes de la implementación.

| ID | Required | Criterio |
| --- | --- | --- |
| R01 | sí | La aplicación FastAPI vive en `api/app.py` y guarda el inventario en `products.csv`. |
| R02 | sí | `GET /inventory` devuelve la lista completa de productos. |
| R03 | sí | `POST /inventory` añade un producto con `name`, `quantity` y `unit`. |
| R04 | sí | `PATCH /inventory/{product_id}` actualiza el stock con `delta`: positivo entra, negativo sale. |
| R05 | sí | `GET /inventory/alerts` devuelve los productos con cantidad por debajo de un umbral configurable. El valor por defecto es 10. |
| R06 | sí | Todos los endpoints devuelven un código HTTP adecuado y un mensaje descriptivo cuando hay un error. |
| R07 | sí | El catálogo guarda nombre, cantidad y unidad de medida. |
| R08 | sí | Cada endpoint usado por el agente está definido como tool con `name`, `description` y `parameters` tipados. |
| R09 | sí | `agent.py` implementa a mano el bucle Observar → Pensar → Actuar → Actualizar → Repetir. |
| R10 | sí | El historial de la conversación se mantiene en memoria durante la sesión. |
| R11 | sí | Cuando llega una tool seleccionada, el agente llama al endpoint de la API que le corresponde. |
| R12 | sí | El resultado de esa llamada se inyecta en el historial antes de la siguiente iteración. |
| R13 | sí | El bucle termina de forma limpia cuando la respuesta no trae tool calls pendientes. |
| R14 | sí | La CLI lee el mensaje de la persona en la terminal e imprime la respuesta del agente. |
| R15 | sí | Hay al menos una interacción de varios pasos en la misma sesión (alta de un producto y, a continuación, consulta de alertas). |
| R16 | sí | No se usa ningún framework de agentes (LangChain, LlamaIndex, AutoGen u otro equivalente). El bucle está escrito en Python. |
| R17 | sí | Cada evento (mensaje de la persona, respuesta del agente, llamada a tool y resultado de tool) se añade a `conversation_log.csv`. |
| R18 | sí | El CSV tiene los campos `actor`, `message`, `tool_call` y `timestamp`. |
| R19 | sí | `actor` es `user`, `agent` o `tool`. `tool_call` va vacío cuando no aplica. `timestamp` es ISO 8601. |
| R20 | sí | El registro es append-only: una sesión nueva añade filas y no borra las anteriores. |
| R21 | sí | El README explica cómo arrancar la API y el agente, cómo pararlos y cómo relanzar el agente sin perder el registro. |
| R22 | sí | Los comandos de arranque del enunciado se conservan: `uvicorn api.app:app --reload` y `python agent.py`. |
| R23 | sí | Las dependencias pedidas son FastAPI, Uvicorn, el SDK `openai` y `python-dotenv`. El fichero `.env` está en `.gitignore` y no se versiona. |
| R24 | sí | La integración live lee `GROQ_API_KEY` del entorno y construye un cliente del SDK OpenAI con la `base_url` compatible de Groq. La clave no se imprime. |
| R25 | sí | La procedencia de `4GeeksAcademy/python-hello` queda documentada con el commit de origen. No se inventan licencia, autores ni colaboradores. |
| R26 | sí | Los productos de `products.csv` siguen disponibles después de reiniciar el proceso de la API. |
| R27 | sí | Una llamada real al LLM en Groq, en la que el modelo selecciona las tools. |
| R28 | sí | El modo mock es explícito y va rotulado. No sirve para dar por cumplido R27. |
| R29 | sí | SIGNAL se aplica al README, a la salida de terminal y a los mensajes de la API. No hay UI: el lockup no aplica y eso queda escrito en `DESIGN-QA.md`. |

## Qué cubre cada bloque del enunciado

- API, cuatro endpoints y errores: R01–R07.
- Tools, bucle, memoria, parada limpia y CLI: R08–R14.
- Paso múltiple y prohibición de frameworks: R15–R16.
- `conversation_log.csv`: R17–R20.
- Arranque, stack, `.env` y plantilla: R21–R26.
- Llamada real al modelo: R27. Si no hay clave, el estado es BLOCKED. Un mock, un doble de pruebas o un cliente falso no pueden marcarlo PASS.
- Reglas de fase 2 que acompañan al enunciado: R28–R29.

## Fuera de la rúbrica obligatoria

Los extras (comando de ayuda, resumen legible de alertas, transcripción mock, límite de iteraciones y escritura CSV segura) se juzgan en `EXCELLENCE_REVIEW.md`. No reemplazan ninguna fila de esta tabla.
