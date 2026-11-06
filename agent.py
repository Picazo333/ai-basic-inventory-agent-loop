"""Agente de inventario.

El bucle Observar → Pensar → Actuar → Actualizar → Repetir está en este
fichero. No hay un framework de agentes: Pensar llama al SDK OpenAI
apuntando a Groq, o a una regla local si se arranca con --mock.

--mock no llama a un modelo y no demuestra que el modelo seleccione tools.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
from openai import OpenAI

from alert_format import format_quantity
from safe_csv import LOG_FIELDS, append_row

ROOT = Path(__file__).resolve().parent
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_API_URL = "http://127.0.0.1:8000"
ACTORS = {"user", "agent", "tool"}

HELP_COMMANDS = {"ayuda", "help", "?"}
ALERT_COMMANDS = {"alertas", "alerts", "alerta"}
EXIT_COMMANDS = {"salir", "exit", "quit", "q"}

MOCK_DEMO_LINES = (
    "ayuda",
    "alertas",
    "Acaban de llegar 30 unidades de leche de avena",
    "Vendimos 12 bolsas de café arábica",
    "¿Qué productos están por agotarse?",
    "salir",
)

SYSTEM_PROMPT = """Eres el asistente de inventario de una tienda de suministros para cafeterías. Carla habla contigo para registrar entregas, anotar ventas y saber qué productos están bajos.

Reglas:
- No inventes cantidades ni ids. Si falta un dato, llama a una tool.
- Si hay que cambiar el stock y solo conoces el nombre, llama primero a list_inventory, localiza el id y después llama a update_stock.
- Un delta positivo es una entrada. Un delta negativo es una venta o una salida.
- Si el producto no existe y Carla registra una llegada, llama a add_product.
- Si pregunta qué está por agotarse o pide alertas, llama a get_low_stock_alerts.
- El umbral por defecto de la API es 10. La comparación es numérica y no convierte unidades.
- Cuando tengas los resultados, responde en el idioma del mensaje, en pocas frases, y usa solo cifras devueltas por las tools.
- Si una tool devuelve un error, explícalo y no simules que el stock cambió.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_inventory",
            "description": (
                "Devuelve todos los productos con id, nombre, cantidad y unidad. "
                "Úsala antes de actualizar el stock cuando solo conoces el nombre."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_product",
            "description": "Registra un producto nuevo. La API rechaza un nombre que ya existe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre del producto."},
                    "quantity": {"type": "number", "description": "Cantidad inicial, cero o mayor."},
                    "unit": {
                        "type": "string",
                        "description": "Unidad de medida, por ejemplo unidades, kg, litros o bolsas.",
                    },
                },
                "required": ["name", "quantity", "unit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_stock",
            "description": (
                "Suma un delta al stock de un id existente. "
                "Positivo: entrada de mercancía. Negativo: venta o salida."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "string",
                        "description": "Id del producto tal como lo devuelve list_inventory.",
                    },
                    "delta": {
                        "type": "number",
                        "description": "Variación de stock. No puede ser cero.",
                    },
                },
                "required": ["product_id", "delta"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_low_stock_alerts",
            "description": (
                "Devuelve los productos cuya cantidad es menor que el umbral. "
                "Si omites el umbral, la API usa 10. No convierte unidades."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "description": "Umbral numérico. Si se omite, la API usa 10.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]

_STOCK_PATTERNS = (
    (
        "in",
        re.compile(
            r"(?:acaban de llegar|han llegado|llegaron|llegó|llego|recibimos|recibí|recibi|"
            r"recibido|received|we just received)\s+(\d+(?:[.,]\d+)?)\s+(\S+)\s+(?:de|of)\s+(.+)",
            re.IGNORECASE,
        ),
    ),
    (
        "out",
        re.compile(
            r"(?:vendimos|vendí|vendi|hemos vendido|sold|we sold)\s+"
            r"(\d+(?:[.,]\d+)?)\s+(\S+)\s+(?:de|of)\s+(.+)",
            re.IGNORECASE,
        ),
    ),
    (
        "new",
        re.compile(
            r"(?:registra|añade|agrega|add|crea)\s+(\d+(?:[.,]\d+)?)\s+(\S+)\s+(?:de|of)\s+(.+)",
            re.IGNORECASE,
        ),
    ),
)


class ConfigError(RuntimeError):
    """Falta un dato de arranque que la persona tiene que corregir."""


RequestFunc = Callable[..., dict]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ThinkResult:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_path() -> Path:
    raw = os.environ.get("CONVERSATION_LOG_PATH")
    if raw:
        return Path(raw)
    return ROOT / "conversation_log.csv"


def log_event(path: Path, actor: str, message: str, tool_call: str, clock: Callable[[], str] = iso_now) -> None:
    if actor not in ACTORS:
        raise ValueError(f"actor no permitido: {actor}")
    append_row(
        path,
        LOG_FIELDS,
        {
            "actor": actor,
            "message": message,
            "tool_call": tool_call or "",
            "timestamp": clock(),
        },
    )


def missing_key_message() -> str:
    return (
        "No hay GROQ_API_KEY. El modo live no llama al modelo.\n"
        "Crea un .env a partir de .env.example o exporta la variable.\n"
        "Para una demo determinista, arranca con: python agent.py --mock\n"
        "El modo mock no selecciona tools con un LLM."
    )


def build_client() -> OpenAI:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise ConfigError(missing_key_message())
    return OpenAI(api_key=key, base_url=GROQ_BASE_URL)


def resolve_model() -> str:
    return os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_MODEL


def resolve_max_iterations(explicit: int | None = None) -> int:
    if explicit is None:
        raw = os.environ.get("MAX_TOOL_ITERATIONS", "8").strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ConfigError("MAX_TOOL_ITERATIONS tiene que ser un entero.") from exc
    else:
        value = explicit
    if value < 1:
        raise ConfigError("MAX_TOOL_ITERATIONS tiene que ser 1 o mayor.")
    return value


def help_text() -> str:
    return "\n".join(
        [
            "Comando local: ayuda. No llama al modelo.",
            "",
            "Comandos",
            "  ayuda     Muestra esta ayuda.",
            "  alertas   Consulta GET /inventory/alerts y muestra el resumen.",
            "  salir     Cierra la sesión. conversation_log.csv no se borra.",
            "",
            "Frases que el modo mock entiende",
            "  Acaban de llegar 30 unidades de leche de avena",
            "  Vendimos 12 bolsas de café arábica",
            "  ¿Qué productos están por agotarse?",
            "  Registra 15 cajas de tapas y dime las alertas",
            "  lista el inventario",
            "",
            "Arranque",
            "  Terminal 1: uvicorn api.app:app --reload",
            "  Terminal 2: python agent.py",
            "  Demo sin clave: python agent.py --mock",
            "",
            "El modo mock elige las tools con una regla local.",
            "No demuestra que un modelo las seleccione.",
            "El modo live necesita GROQ_API_KEY y no imprime la clave.",
        ]
    )


def banner(*, mode: str, base_url: str, model: str) -> str:
    lines = ["Inventario de suministros"]
    if mode == "mock":
        lines.extend(
            [
                "Modo: MOCK",
                "No hay llamada a un LLM. Las tools las elige una regla local determinista.",
                "Este modo no demuestra que el modelo seleccione tools.",
            ]
        )
    else:
        lines.extend(
            [
                "Modo: LIVE",
                f"Modelo: {model}",
                "Cliente OpenAI compatible apuntando a https://api.groq.com/openai/v1.",
                "La clave se lee de GROQ_API_KEY y no se muestra.",
            ]
        )
    lines.extend([f"API: {base_url}", "Comandos: ayuda, alertas, salir."])
    return "\n".join(lines)


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    outgoing = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(outgoing, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        status = exc.code
    except urllib.error.URLError:
        return {
            "status_code": None,
            "body": {
                "detail": (
                    "No pude contactar con la API. "
                    "Siguiente paso: en otra terminal, uvicorn api.app:app --reload."
                )
            },
        }
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {"detail": "La API no devolvió JSON."}
    return {"status_code": status, "body": body}


def execute_tool(name: str, arguments: dict, *, base_url: str, request: RequestFunc, timeout: float) -> dict:
    base = base_url.rstrip("/")
    try:
        if name == "list_inventory":
            return request("GET", f"{base}/inventory", None, timeout)
        if name == "add_product":
            payload = {
                "name": arguments["name"],
                "quantity": arguments["quantity"],
                "unit": arguments["unit"],
            }
            return request("POST", f"{base}/inventory", payload, timeout)
        if name == "update_stock":
            if isinstance(arguments.get("delta"), bool):
                return {"status_code": None, "body": {"detail": "delta tiene que ser un número."}}
            product_id = quote(str(arguments["product_id"]), safe="")
            payload = {"delta": arguments["delta"]}
            return request("PATCH", f"{base}/inventory/{product_id}", payload, timeout)
        if name == "get_low_stock_alerts":
            url = f"{base}/inventory/alerts"
            threshold = arguments.get("threshold")
            if threshold is not None:
                if isinstance(threshold, bool):
                    return {"status_code": None, "body": {"detail": "threshold tiene que ser un número."}}
                url = f"{url}?{urlencode({'threshold': threshold})}"
            return request("GET", url, None, timeout)
    except KeyError as exc:
        missing = exc.args[0]
        return {"status_code": None, "body": {"detail": f"Faltan argumentos para {name}: {missing}."}}
    return {"status_code": None, "body": {"detail": f"La tool '{name}' no está definida."}}


def ensure_system(history: list[dict]) -> None:
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})


def live_think(client: OpenAI, model: str, messages: list[dict]) -> ThinkResult:
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0,
        )
    except Exception as exc:
        return ThinkResult(
            content=(
                "La llamada al modelo no se completó "
                f"({exc.__class__.__name__}). Revisa la clave, el modelo y la red. "
                "La clave no se muestra."
            )
        )
    message = response.choices[0].message
    calls: list[ToolCall] = []
    for index, tool_call in enumerate(getattr(message, "tool_calls", None) or []):
        function = tool_call.function
        raw_arguments = function.arguments or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {"_invalid_json": raw_arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        calls.append(
            ToolCall(
                id=getattr(tool_call, "id", None) or f"call-{index}",
                name=function.name,
                arguments=arguments,
            )
        )
    return ThinkResult(content=message.content, tool_calls=calls)


def _clean_name(name: str) -> str:
    text = " ".join(name.strip().split())
    text = text.strip("?.!,;:\"'")
    text = re.sub(
        r"\s+y\s+(?:dime|muestra|consulta|enseña|revisa|quiero|luego).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _parse_stock(text: str) -> tuple[str, Decimal, str, str] | None:
    for kind, pattern in _STOCK_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        quantity = Decimal(match.group(1).replace(",", "."))
        unit = match.group(2)
        name = _clean_name(match.group(3))
        if name:
            return kind, quantity, unit, name
    return None


def _wants_alerts(text: str) -> bool:
    return re.search(r"alert|agot|running low|stock bajo|por debajo", text, re.IGNORECASE) is not None


def _wants_list(text: str) -> bool:
    return re.search(r"\b(lista|inventario|catálogo|catalogo|list)\b", text, re.IGNORECASE) is not None


def _threshold(text: str) -> float | None:
    match = re.search(r"(?:umbral|threshold)\s+(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if match is None:
        return None
    return float(match.group(1).replace(",", "."))


def _json_qty(value: Decimal) -> int | float:
    text = format_quantity(value)
    if text.startswith("-"):
        number = text[1:]
        if "." not in number:
            return -int(number)
        return -float(number)
    if "." not in text:
        return int(text)
    return float(text)


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _tool_events(messages: list[dict]) -> list[dict]:
    last_user = 0
    for index, message in enumerate(messages):
        if message.get("role") == "user":
            last_user = index
    pending: list[dict] = []
    events: list[dict] = []
    for message in messages[last_user + 1 :]:
        if message.get("role") == "assistant":
            pending.extend(message.get("tool_calls") or [])
        elif message.get("role") == "tool" and pending:
            tool_call = pending.pop(0)
            function = tool_call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            try:
                result = json.loads(message.get("content") or "{}")
            except json.JSONDecodeError:
                result = {"status_code": None, "body": {"detail": message.get("content")}}
            events.append({"name": function.get("name"), "arguments": arguments, "result": result})
    return events


def _ok(result: dict) -> bool:
    status = result.get("status_code")
    return isinstance(status, int) and 200 <= status < 300


def _detail(result: dict) -> str:
    body = result.get("body") or {}
    if isinstance(body, dict) and body.get("detail"):
        return str(body["detail"])
    status = result.get("status_code")
    if status is None:
        return "No pude contactar con la API."
    return f"La API respondió {status}."


def _find_product(products: list[dict], name: str) -> dict | None:
    target = name.casefold()
    for product in products:
        if str(product.get("name", "")).casefold() == target:
            return product
    return None


def _stock_sentence(event: dict) -> str:
    body = event["result"]["body"]
    if event["name"] == "update_stock":
        product = body["product"]
        delta = Decimal(str(body.get("delta")))
        movement = "entrada" if delta > 0 else "salida"
        return (
            f"{product['name']} queda en {format_quantity(product['quantity'])} {product['unit']} "
            f"({movement} de {format_quantity(abs(delta))})."
        )
    return (
        f"He registrado {body['name']} con {format_quantity(body['quantity'])} {body['unit']} "
        f"(id {body['id']})."
    )


def _mock_call(call_id: str, name: str, arguments: dict) -> ThinkResult:
    return ThinkResult(tool_calls=[ToolCall(call_id, name, arguments)])


def _mock_alerts(text: str, events: list[dict], call_id: str) -> ThinkResult:
    done = [event for event in events if event["name"] == "get_low_stock_alerts"]
    if not done:
        arguments: dict = {}
        threshold = _threshold(text)
        if threshold is not None:
            arguments["threshold"] = threshold
        return _mock_call(call_id, "get_low_stock_alerts", arguments)
    result = done[-1]["result"]
    if not _ok(result):
        return ThinkResult(content=_detail(result))
    summary = (result.get("body") or {}).get("summary") or "La API no devolvió un resumen."
    return ThinkResult(content=summary)


def _mock_list(events: list[dict], call_id: str) -> ThinkResult:
    done = [event for event in events if event["name"] == "list_inventory"]
    if not done:
        return _mock_call(call_id, "list_inventory", {})
    result = done[-1]["result"]
    if not _ok(result):
        return ThinkResult(content=_detail(result))
    products = (result.get("body") or {}).get("products") or []
    if not products:
        return ThinkResult(content="El inventario no tiene productos.")
    lines = ["Inventario:"]
    for product in products:
        lines.append(
            f"- {product['name']}: {format_quantity(product['quantity'])} {product['unit']} (id {product['id']})"
        )
    return ThinkResult(content="\n".join(lines))


def _mock_stock(text: str, stock: tuple[str, Decimal, str, str], events: list[dict], call_id: str) -> ThinkResult:
    kind, quantity, unit, name = stock
    names = {event["name"] for event in events}
    if kind != "new" and "list_inventory" not in names:
        return _mock_call(call_id, "list_inventory", {})

    if "update_stock" not in names and "add_product" not in names:
        if kind == "new":
            return _mock_call(
                call_id,
                "add_product",
                {"name": name, "quantity": _json_qty(quantity), "unit": unit},
            )
        listed = next(event for event in events if event["name"] == "list_inventory")
        if not _ok(listed["result"]):
            return ThinkResult(content=_detail(listed["result"]))
        products = (listed["result"].get("body") or {}).get("products") or []
        product = _find_product(products, name)
        if product is None:
            if kind == "out":
                return ThinkResult(content=f"No está en el inventario: {name}. No he cambiado el stock.")
            return _mock_call(
                call_id,
                "add_product",
                {"name": name, "quantity": _json_qty(quantity), "unit": unit},
            )
        if str(product["unit"]).casefold() != unit.casefold():
            return ThinkResult(
                content=(
                    f"{product['name']} está registrado en {product['unit']}, no en {unit}. "
                    "No he cambiado el stock porque no convierto unidades."
                )
            )
        delta = quantity if kind == "in" else -quantity
        return _mock_call(
            call_id,
            "update_stock",
            {"product_id": str(product["id"]), "delta": _json_qty(delta)},
        )

    mutation = next(event for event in events if event["name"] in {"update_stock", "add_product"})
    if not _ok(mutation["result"]):
        return ThinkResult(content=_detail(mutation["result"]))
    sentence = _stock_sentence(mutation)
    if _wants_alerts(text):
        return _append_alerts(text, events, call_id, sentence)
    return ThinkResult(content=sentence)


def _append_alerts(text: str, events: list[dict], call_id: str, sentence: str) -> ThinkResult:
    done = [event for event in events if event["name"] == "get_low_stock_alerts"]
    if not done:
        arguments: dict = {}
        threshold = _threshold(text)
        if threshold is not None:
            arguments["threshold"] = threshold
        return _mock_call(call_id, "get_low_stock_alerts", arguments)
    result = done[-1]["result"]
    if not _ok(result):
        return ThinkResult(content=sentence + "\n\n" + _detail(result))
    summary = (result.get("body") or {}).get("summary") or ""
    return ThinkResult(content=sentence + "\n\n" + summary)


def mock_think(messages: list[dict]) -> ThinkResult:
    """Regla local determinista.

    No llama a un modelo y no demuestra selección de tools por un LLM.
    """
    text = _last_user_text(messages)
    events = _tool_events(messages)
    user_turns = sum(1 for message in messages if message.get("role") == "user")
    call_id = f"mock-{user_turns}-{len(events) + 1}"
    stock = _parse_stock(text)
    if stock is not None:
        return _mock_stock(text, stock, events, call_id)
    if _wants_alerts(text):
        return _mock_alerts(text, events, call_id)
    if _wants_list(text):
        return _mock_list(events, call_id)
    return ThinkResult(
        content=(
            "Esta regla local no entiende esa frase. "
            "Prueba con «ayuda» o con una frase como «Vendimos 2 kg de azúcar». "
            "Con GROQ_API_KEY, el modo live envía el texto al modelo."
        )
    )


def run_turn(
    user_text: str,
    history: list[dict],
    think: Callable[[list[dict]], ThinkResult],
    *,
    base_url: str,
    log_file: Path,
    request: RequestFunc,
    max_iterations: int = 8,
    clock: Callable[[], str] = iso_now,
    timeout: float = 30.0,
) -> str:
    """Un mensaje de la persona: Observar → Pensar → Actuar → Actualizar → Repetir."""
    ensure_system(history)
    # Observar
    history.append({"role": "user", "content": user_text})
    log_event(log_file, "user", user_text, "", clock)

    for _iteration in range(max_iterations):
        # Pensar
        result = think(history)
        if not result.tool_calls:
            text = (result.content or "").strip() or "No he recibido una respuesta con contenido."
            history.append({"role": "assistant", "content": text})
            log_event(log_file, "agent", text, "", clock)
            return text

        # Actuar
        history.append(
            {
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in result.tool_calls
                ],
            }
        )
        for call in result.tool_calls:
            log_event(log_file, "agent", json.dumps(call.arguments, ensure_ascii=False), call.name, clock)
            outcome = execute_tool(
                call.name,
                call.arguments,
                base_url=base_url,
                request=request,
                timeout=timeout,
            )
            encoded = json.dumps(outcome, ensure_ascii=False)
            log_event(log_file, "tool", encoded, call.name, clock)
            # Actualizar: el resultado entra en el historial antes de la siguiente vuelta.
            history.append({"role": "tool", "tool_call_id": call.id, "content": encoded})
        # Repetir

    text = (
        f"He parado el bucle al llegar al límite de {max_iterations} iteraciones de tools. "
        "La respuesta seguía pidiendo tools. "
        "Reformula el pedido o sube MAX_TOOL_ITERATIONS."
    )
    history.append({"role": "assistant", "content": text})
    log_event(log_file, "agent", text, "", clock)
    return text


def _present(mode: str, text: str) -> str:
    label = "mock" if mode == "mock" else "live"
    return f"[{label}]\n{text}"


def _alerts_body(base_url: str, request: RequestFunc, timeout: float) -> str:
    outcome = request("GET", f"{base_url.rstrip('/')}/inventory/alerts", None, timeout)
    if outcome.get("status_code") == 200 and isinstance(outcome.get("body"), dict):
        summary = outcome["body"].get("summary") or "La API no devolvió un resumen."
        return (
            "Comando local: consulta directa a GET /inventory/alerts. "
            "No es una selección del modelo.\n\n" + summary
        )
    detail = _detail(outcome)
    return (
        "Comando local: no pude consultar las alertas.\n"
        f"{detail}\n"
        "Siguiente paso: arranca la API con uvicorn api.app:app --reload."
    )


def run_cli(
    lines: Iterator[str | None],
    output: Callable[[str], None],
    *,
    mode: str,
    base_url: str,
    log_file: Path,
    think: Callable[[list[dict]], ThinkResult],
    request: RequestFunc,
    max_iterations: int,
    model: str,
    clock: Callable[[], str] = iso_now,
    timeout: float = 30.0,
) -> None:
    output(banner(mode=mode, base_url=base_url, model=model))
    history: list[dict] = []
    for raw in lines:
        if raw is None:
            break
        text = raw.strip()
        if not text:
            continue
        output(f"> {text}")
        folded = text.casefold()
        if folded in EXIT_COMMANDS:
            farewell = "Sesión cerrada. conversation_log.csv conserva las filas."
            output(f"[local]\n{farewell}")
            break
        if folded in HELP_COMMANDS:
            body = help_text()
            log_event(log_file, "user", text, "", clock)
            log_event(log_file, "agent", body, "", clock)
            output(f"[local]\n{body}")
            continue
        if folded in ALERT_COMMANDS:
            body = _alerts_body(base_url, request, timeout)
            log_event(log_file, "user", text, "", clock)
            log_event(log_file, "agent", body, "", clock)
            output(f"[local]\n{body}")
            continue
        reply = run_turn(
            text,
            history,
            think,
            base_url=base_url,
            log_file=log_file,
            request=request,
            max_iterations=max_iterations,
            clock=clock,
            timeout=timeout,
        )
        output(_present(mode, reply))


def render_session(
    lines: tuple[str, ...] | list[str],
    *,
    mode: str = "mock",
    request: RequestFunc,
    log_file: Path,
    base_url: str = "http://127.0.0.1:8000",
    max_iterations: int = 8,
    clock: Callable[[], str] | None = None,
) -> str:
    if mode != "mock":
        raise ConfigError("render_session solo genera la demo rotulada como mock.")
    chunks: list[str] = []
    run_cli(
        iter(lines),
        chunks.append,
        mode=mode,
        base_url=base_url,
        log_file=log_file,
        think=mock_think,
        request=request,
        max_iterations=max_iterations,
        model=resolve_model(),
        clock=clock or (lambda: "2026-11-06T08:00:00+00:00"),
        timeout=5.0,
    )
    return "\n".join(chunks) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python agent.py",
        description=(
            "Agente de inventario. El bucle de tools está en agent.py. "
            "Sin --mock intenta llamar a Groq con GROQ_API_KEY."
        ),
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Usa la regla local determinista. No llama a Groq y no demuestra selección del modelo.",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("INVENTORY_API_URL", DEFAULT_API_URL),
        help="URL base de la API. Por defecto http://127.0.0.1:8000.",
    )
    parser.add_argument("--log", default=None, help="Ruta de conversation_log.csv.")
    parser.add_argument("--max-iterations", type=int, default=None, help="Máximo de vueltas con tools.")
    return parser.parse_args(argv)


def iter_stdin() -> Iterator[str]:
    while True:
        try:
            yield input()
        except EOFError:
            return


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env", override=False)
    try:
        args = parse_args(argv)
        mode = "mock" if args.mock else "live"
        iterations = resolve_max_iterations(args.max_iterations)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if mode == "live" and not os.environ.get("GROQ_API_KEY", "").strip():
        print(missing_key_message(), file=sys.stderr)
        return 2

    model = resolve_model()
    if mode == "mock":
        think: Callable[[list[dict]], ThinkResult] = mock_think
    else:
        client = build_client()

        def think(messages: list[dict], _client: OpenAI = client, _model: str = model) -> ThinkResult:
            return live_think(_client, _model, messages)

    destination = Path(args.log) if args.log else log_path()
    try:
        run_cli(
            iter_stdin(),
            print,
            mode=mode,
            base_url=args.api_url,
            log_file=destination,
            think=think,
            request=request_json,
            max_iterations=iterations,
            model=model,
        )
    except KeyboardInterrupt:
        print("\n[local]\nSesión interrumpida. El registro escrito hasta ahora se conserva.")
        return 130
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
