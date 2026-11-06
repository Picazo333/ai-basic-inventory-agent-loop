"""Resumen legible de alertas de stock.

Lo usan la API y el comando local `alertas`. La comparación es numérica:
10 kg y 10 unidades se miran como 10, sin convertir una unidad en otra.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def format_quantity(value: object) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    quantized = number.quantize(Decimal("0.001"))
    if quantized == 0:
        return "0"
    if quantized == quantized.to_integral():
        return str(quantized.to_integral())
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return text or "0"


def format_alert_summary(alerts: list[dict], threshold: object) -> str:
    threshold_text = format_quantity(threshold)
    header = (
        "Alertas de stock\n"
        f"Umbral: {threshold_text}. La comparación es numérica y no convierte unidades."
    )
    if not alerts:
        return (
            f"{header}\n\n"
            "Ningún producto está por debajo del umbral.\n"
            "Siguiente paso: anota una venta o vuelve a consultar cuando cambie el stock."
        )
    ordered = sorted(alerts, key=lambda item: (Decimal(str(item["quantity"])), str(item["name"]).casefold()))
    width = max(len(str(item["name"])) for item in ordered)
    count = len(ordered)
    noun = "producto" if count == 1 else "productos"
    lines = [header, "", f"{count} {noun} por debajo del umbral:"]
    for item in ordered:
        lines.append(
            f"  {str(item['name']).ljust(width)}  {format_quantity(item['quantity'])} {item['unit']}"
        )
    lines.append("")
    lines.append("Siguiente paso: di qué entrega o venta hay que anotar.")
    return "\n".join(lines)
