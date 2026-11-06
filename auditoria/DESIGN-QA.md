# DESIGN-QA

Perfil académico SIGNAL sobre un proyecto sin interfaz. El enunciado dice que el diseño visual no se evalúa y que basta la terminal. No se añadió una pantalla para colocar marca.

## Decisión

No hay UI. `/docs` y `/redoc` están desactivados (`api/app.py`, `docs_url=None`, `redoc_url=None`). `GET /openapi.json` es JSON. El lockup 4Geeks × Divinivid no se copia y no se dibuja: la regla de esta entrega es que, sin UI, el lockup no aplica.

No se redistribuyen SVG ni PNG de marca. No hay hash de lockup que verificar porque ningún asset de marca entra en el runtime ni en el README.

## Qué sí se revisó

| Superficie | Qué se pidió a SIGNAL | Resultado | Evidencia |
| --- | --- | --- | --- |
| README | Jerarquía, comandos reproducibles, límites explícitos, sin eslogan | Hecho | `README.md` |
| Terminal | Modo visible, comandos locales, error con el paso siguiente, sin color como único canal | Hecho | `evidence/cli-help.txt`, `evidence/cli-live-without-key.txt`, `evidence/cli-mock-http.txt`, `docs/demo-mock-transcript.txt` |
| API | Frases de error, códigos HTTP, resumen de alertas legible | Hecho | `evidence/api-transcript.txt`, `tests/test_api.py` |
| Datos | El resumen de alertas sale de la API. La demo mock no inventa cifras | Hecho | `docs/demo-mock-transcript.txt` |

Estados comprobados en la CLI: arranque mock, ayuda, alertas con datos, frase reconocida, cierre con `salir`, y arranque live sin clave (código 2). En la API: 200, 201, 400 cubierto por tests, 404 de id, 404 de ruta, 409 y 422 cubiertos por tests.

## No aplica

| Comprobación | Motivo |
| --- | --- |
| Capturas a 390, 768 y 1280 px | No hay vista. |
| Vídeo de recorrido | No hay vista. |
| Lighthouse, LCP, CLS, TBT/INP | No hay build de frontend ni página HTML. Medir el JSON de la API no describe una pantalla. |
| Contraste AA, foco, teclado de componentes, axe | No hay controles gráficos. La terminal no codifica el estado solo con color. |
| `prefers-reduced-motion` y fichas de motion | No hay animación. |
| SEO de landing, canonical, sitemap, schema | No hay sitio público. |
| Presupuesto de JS y CSS | No hay assets de cliente. |

Estas filas son NO APLICA. No están contadas como PASS de una UI.
