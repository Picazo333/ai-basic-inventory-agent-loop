# Revisión de excelencia

Los extras están por debajo de la rúbrica. No cambian los endpoints, el bucle manual ni el formato del registro.

## Extra visible — IMPLEMENTADO

Comando de ayuda, resumen legible de alertas y transcripción rotulada como mock.

- `ayuda` y `python agent.py --help` explican comandos, frases y la diferencia entre mock y live. No llaman al modelo. Evidencia: `agent.py` `help_text` (línea 256), `evidence/cli-help.txt`, el bloque `[local]` de `docs/demo-mock-transcript.txt`.
- `alertas` consulta `GET /inventory/alerts` y muestra el texto de `alert_format.py`: umbral, lista alineada y el siguiente paso. El mismo texto viaja en el campo `summary` de la API. Evidencia: `alert_format.py`; la demo; `tests/test_cli_mock.py` `test_help_and_alerts_are_local_commands`.
- `docs/demo-mock-transcript.txt` abre con `Modo: MOCK` y avisa de que la regla local no demuestra la selección del modelo. El test `test_mock_demo_is_labeled_and_matches_the_transcript` compara el fichero con una ejecución nueva. `evidence/cli-mock-http.txt` es otra pasada, esta vez con `python agent.py --mock` contra Uvicorn.

## Extra técnico — IMPLEMENTADO

Límite de iteraciones y escritura CSV segura, con tests.

- `MAX_TOOL_ITERATIONS` (defecto 8, también `--max-iterations`) corta el bucle si `think` sigue pidiendo tools. El mensaje dice el tope y cómo subirlo. Evidencia: `agent.py` 723-730; `tests/test_agent_loop.py` `test_iteration_limit_stops_the_tool_loop` (con tope 2, `think` se llama exactamente dos veces).
- `products.csv` se reemplaza con fichero temporal, `fsync` y `os.replace` bajo `fcntl.flock`. Si `os.replace` falla, el CSV anterior permanece y el temporal se borra. `conversation_log.csv` solo se abre en append. Evidencia: `safe_csv.py`; `tests/test_csv_safety.py` (cita, cabecera sin salto de línea, reemplazo fallido, 160 appends concurrentes y 100 incrementos bajo el mismo bloqueo).

## Otras ideas

| Idea | Decisión | Motivo |
| --- | --- | --- |
| Stock separado por los dos locales del relato | REJECT | El enunciado pide nombre, cantidad y unidad, y cuatro endpoints sobre un inventario. Un reparto por local cambiaría el contrato sin un criterio que lo exija. El límite queda escrito en el README. |
| Dejar activa la UI de Swagger para enseñar la API | REJECT | El enunciado acepta la terminal. Abrir `/docs` crearía una UI y arrastraría el lockup. El contrato queda en el README y en `/openapi.json`. |
| Ejecutar una llamada real a Groq dentro de este extra | DEFER | No hay clave. Hacerla pasar por el mock contradice R27. Cuando exista `GROQ_API_KEY`, el modo por defecto de `python agent.py` ya usa el cliente live. |
