# Auditoría final

Estado: **PENDIENTE_REVISION_ORQUESTADOR**.

No hay merge y no se envió nada a un LMS.

## Resultado

| | |
| --- | --- |
| Criterios | 29 |
| PASS | 28 |
| FAIL | 0 |
| BLOCKED | 1 (R27) |

R27 permanece BLOCKED: no hay `GROQ_API_KEY`, así que no hubo llamada a Groq ni una selección de tools hecha por el modelo. El detalle está en `auditoria/RUBRIC_JUSTIFICATION.md`.

## Contraste con el enunciado

- `api/app.py` expone `GET /inventory`, `POST /inventory`, `PATCH /inventory/{product_id}` y `GET /inventory/alerts`.
- `products.csv` sobrevive a otro proceso y a otro Uvicorn (`tests/test_persistence.py`).
- `agent.py` contiene el bucle Observar → Pensar → Actuar → Actualizar → Repetir.
- Las tools tienen nombre, descripción y parámetros tipados.
- El resultado de cada tool vuelve al historial antes de la siguiente vuelta.
- `conversation_log.csv` es append-only y usa `actor`, `message`, `tool_call`, `timestamp`.
- Hay un turno de varios pasos: alta y, después, alertas.
- No hay framework de agentes.
- El README documenta los dos procesos, la parada y el relanzamiento.
- La procedencia de `python-hello` está en `third_party/python-hello/PROVENANCE.md`, commit `142f2a913162efafce897da8bf241fe690f60395`, sin licencia inventada y sin colaboradores añadidos.

## Extras

Visibles y técnicos, ambos implementados. Ver `auditoria/EXCELLENCE_REVIEW.md`.

## SIGNAL

Sin UI. Lockup no aplicado, documentado en `auditoria/DESIGN-QA.md`. Capturas 390/768/1280, vídeo y Lighthouse son NO APLICA.

## Comprobación de cierre

`uv run pytest -o addopts= -v` — 36 passed. Salida en `evidence/pytest.txt`.

La demo limpia, sobre el catálogo del repositorio, está en `docs/demo-mock-transcript.txt`. La sesión HTTP, sobre una copia temporal que antes recibió los curl, está en `evidence/cli-mock-http.txt`. En esa copia Azúcar ya había bajado de 5 kg a 3 kg y existía Tapas. El catálogo versionado sigue con Azúcar a 5 kg y sin Tapas.

## SHA

El hash del commit no cabe dentro del propio commit. El informe de esta ejecución y la descripción del pull request citan `git rev-parse HEAD` después del push.
