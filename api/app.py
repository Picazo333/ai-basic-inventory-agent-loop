"""API REST del inventario.

Los productos viven en `products.csv`. Cada petición lee o escribe ese fichero;
no hay una copia en memoria que se pierda al parar el proceso.
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from alert_format import format_alert_summary, format_quantity
from safe_csv import PRODUCT_FIELDS, apply_rows, read_rows

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="Inventario de suministros",
    version="1.0.0",
    description=(
        "Stock de la tienda de suministros para cafeterías. "
        "Los datos persisten en products.csv. No hay interfaz web: "
        "el contrato es JSON y la conversación ocurre en la CLI."
    ),
    docs_url=None,
    redoc_url=None,
)


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    quantity: float = Field(ge=0, le=1_000_000_000)
    unit: str = Field(min_length=1, max_length=32)

    @field_validator("name", "unit")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            raise ValueError("El texto no puede estar vacío.")
        if any(character in cleaned for character in "\r\n\t"):
            raise ValueError("El texto no puede incluir saltos de línea.")
        return cleaned

    @field_validator("quantity")
    @classmethod
    def finite_quantity(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("La cantidad tiene que ser un número finito.")
        return value


class StockDelta(BaseModel):
    delta: float = Field(ge=-1_000_000_000, le=1_000_000_000)

    @field_validator("delta")
    @classmethod
    def finite_delta(cls, value: float) -> float:
        if isinstance(value, bool) or value != value or value in (float("inf"), float("-inf")):
            raise ValueError("El delta tiene que ser un número finito.")
        return value


def inventory_path() -> Path:
    raw = os.environ.get("PRODUCTS_CSV_PATH")
    if raw:
        return Path(raw)
    return ROOT / "products.csv"


def _decimal(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(status_code=400, detail="La cantidad guardada no es un número.") from exc
    if not number.is_finite():
        raise HTTPException(status_code=400, detail="La cantidad guardada no es un número finito.")
    return number


def _json_number(value: Decimal) -> int | float:
    text = format_quantity(value)
    if "." not in text:
        return int(text)
    return float(text)


def _public(row: dict[str, str]) -> dict[str, object]:
    return {
        "id": row["id"],
        "name": row["name"],
        "quantity": _json_number(_decimal(row["quantity"])),
        "unit": row["unit"],
    }


def _load() -> list[dict[str, str]]:
    return read_rows(inventory_path(), PRODUCT_FIELDS)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if exc.status_code == 404 and detail == "Not Found":
        detail = "Esa ruta no existe. Revisa el método y la ruta en el README."
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    parts: list[str] = []
    for error in exc.errors():
        location = [str(item) for item in error.get("loc", []) if item != "body"]
        field = ".".join(location) or "cuerpo"
        parts.append(f"{field}: {error.get('msg', 'dato no válido')}")
    message = "Datos no válidos. " + " ".join(parts)
    return JSONResponse(status_code=422, content={"detail": message})


@app.get("/")
def service_index() -> dict[str, object]:
    return {
        "service": "Inventario de suministros",
        "storage": "products.csv",
        "endpoints": [
            {"method": "GET", "path": "/inventory"},
            {"method": "POST", "path": "/inventory"},
            {"method": "PATCH", "path": "/inventory/{product_id}"},
            {"method": "GET", "path": "/inventory/alerts"},
        ],
    }


@app.get("/inventory")
def list_inventory() -> dict[str, object]:
    products = [_public(row) for row in _load()]
    products.sort(key=lambda item: int(item["id"]) if str(item["id"]).isdigit() else str(item["id"]))
    return {"products": products}


@app.post("/inventory", status_code=201)
def add_product(payload: ProductIn) -> dict[str, object]:
    created: dict[str, object] = {}
    conflict: dict[str, str] = {}

    def mutate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], bool]:
        for row in rows:
            if row["name"].casefold() == payload.name.casefold():
                conflict["id"] = row["id"]
                conflict["name"] = row["name"]
                return rows, False
        numeric_ids = [int(row["id"]) for row in rows if str(row["id"]).isdigit()]
        next_id = (max(numeric_ids) + 1) if numeric_ids else 1
        quantity = format_quantity(_decimal(payload.quantity))
        new_row = {
            "id": str(next_id),
            "name": payload.name,
            "quantity": quantity,
            "unit": payload.unit,
        }
        created.update(_public(new_row))
        return [*rows, new_row], True

    apply_rows(inventory_path(), PRODUCT_FIELDS, mutate)
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ya existe un producto llamado '{conflict['name']}' (id {conflict['id']}). "
                "Para cambiar el stock usa PATCH con un delta."
            ),
        )
    return created


@app.patch("/inventory/{product_id}")
def update_stock(product_id: str, payload: StockDelta) -> dict[str, object]:
    delta = _decimal(payload.delta)
    if delta == 0:
        raise HTTPException(
            status_code=400,
            detail="El delta es 0. Indica un número positivo para una entrada o negativo para una salida.",
        )

    updated: dict[str, object] = {}
    found = False
    rejected: str | None = None

    def mutate(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], bool]:
        nonlocal found, rejected
        for index, row in enumerate(rows):
            if row["id"] != product_id:
                continue
            found = True
            current = _decimal(row["quantity"])
            result = current + delta
            if result < 0:
                rejected = (
                    f"La cantidad resultante sería {format_quantity(result)}, por debajo de cero. "
                    f"Stock actual de '{row['name']}': {format_quantity(current)} {row['unit']}. "
                    f"Delta recibido: {format_quantity(delta)}."
                )
                return rows, False
            changed = dict(row)
            changed["quantity"] = format_quantity(result)
            updated.update(_public(changed))
            new_rows = list(rows)
            new_rows[index] = changed
            return new_rows, True
        return rows, False

    apply_rows(inventory_path(), PRODUCT_FIELDS, mutate)
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"No existe un producto con id {product_id}. Consulta GET /inventory para ver los id.",
        )
    if rejected:
        raise HTTPException(status_code=400, detail=rejected)
    return {"product": updated, "delta": _json_number(delta)}


@app.get("/inventory/alerts")
def low_stock_alerts(threshold: float = Query(default=10, ge=0, le=1_000_000_000)) -> dict[str, object]:
    if threshold != threshold or threshold in (float("inf"), float("-inf")):
        raise HTTPException(status_code=422, detail="El umbral tiene que ser un número finito mayor o igual que cero.")
    limit = _decimal(threshold)
    alerts = []
    for row in _load():
        if _decimal(row["quantity"]) < limit:
            alerts.append(_public(row))
    alerts.sort(key=lambda item: (Decimal(str(item["quantity"])), str(item["name"]).casefold()))
    public_threshold = _json_number(limit)
    return {
        "threshold": public_threshold,
        "count": len(alerts),
        "alerts": alerts,
        "summary": format_alert_summary(alerts, public_threshold),
    }
