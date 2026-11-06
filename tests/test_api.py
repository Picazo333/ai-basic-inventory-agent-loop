from __future__ import annotations

from safe_csv import PRODUCT_FIELDS, read_rows


def test_index_and_openapi_have_no_html_docs(client):
    index = client.get("/")
    assert index.status_code == 200
    paths = {item["path"] for item in index.json()["endpoints"]}
    assert paths == {"/inventory", "/inventory/{product_id}", "/inventory/alerts"}

    missing = client.get("/docs")
    assert missing.status_code == 404
    assert "ruta no existe" in missing.json()["detail"]
    assert client.get("/redoc").status_code == 404

    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert set(schema.json()["paths"]) >= {"/inventory", "/inventory/alerts", "/inventory/{product_id}"}


def test_post_get_and_duplicate(client, isolate_runtime_files):
    created = client.post("/inventory", json={"name": "  Canela  ", "quantity": 4, "unit": "botes"})
    assert created.status_code == 201
    body = created.json()
    assert body == {"id": "1", "name": "Canela", "quantity": 4, "unit": "botes"}

    listed = client.get("/inventory")
    assert listed.status_code == 200
    assert listed.json()["products"] == [body]

    stored = read_rows(isolate_runtime_files["products"], PRODUCT_FIELDS)
    assert stored == [{"id": "1", "name": "Canela", "quantity": "4", "unit": "botes"}]

    duplicate = client.post("/inventory", json={"name": "canela", "quantity": 1, "unit": "botes"})
    assert duplicate.status_code == 409
    assert "id 1" in duplicate.json()["detail"]
    assert "canela" in duplicate.json()["detail"].casefold()


def test_patch_delta_and_errors(client, isolate_runtime_files):
    client.post("/inventory", json={"name": "Azúcar", "quantity": 5, "unit": "kg"})
    increased = client.patch("/inventory/1", json={"delta": 2})
    assert increased.status_code == 200
    assert increased.json()["delta"] == 2
    assert increased.json()["product"]["quantity"] == 7

    decreased = client.patch("/inventory/1", json={"delta": -3})
    assert decreased.status_code == 200
    assert decreased.json()["product"]["quantity"] == 4

    missing = client.patch("/inventory/99", json={"delta": 1})
    assert missing.status_code == 404
    assert "99" in missing.json()["detail"]

    below = client.patch("/inventory/1", json={"delta": -5})
    assert below.status_code == 400
    assert "por debajo de cero" in below.json()["detail"]
    assert read_rows(isolate_runtime_files["products"], PRODUCT_FIELDS)[0]["quantity"] == "4"

    zero = client.patch("/inventory/1", json={"delta": 0})
    assert zero.status_code == 400
    assert "delta" in zero.json()["detail"].casefold()


def test_validation_messages(client):
    missing = client.post("/inventory", json={"quantity": 1, "unit": "kg"})
    assert missing.status_code == 422
    assert "name" in missing.json()["detail"]
    assert "Datos no válidos" in missing.json()["detail"]

    negative = client.post("/inventory", json={"name": "Sal", "quantity": -1, "unit": "kg"})
    assert negative.status_code == 422

    empty = client.post("/inventory", json={"name": "   ", "quantity": 1, "unit": "kg"})
    assert empty.status_code == 422

    bad_threshold = client.get("/inventory/alerts", params={"threshold": -1})
    assert bad_threshold.status_code == 422
    assert "threshold" in bad_threshold.json()["detail"]


def test_alerts_threshold_is_strict_and_configurable(client):
    client.post("/inventory", json={"name": "Bajo", "quantity": 9, "unit": "unidades"})
    client.post("/inventory", json={"name": "Justo", "quantity": 10, "unit": "unidades"})
    client.post("/inventory", json={"name": "Alto", "quantity": 11, "unit": "kg"})

    default = client.get("/inventory/alerts")
    assert default.status_code == 200
    payload = default.json()
    assert payload["threshold"] == 10
    assert [item["name"] for item in payload["alerts"]] == ["Bajo"]
    assert payload["count"] == 1
    assert "Bajo" in payload["summary"]
    assert "Justo" not in payload["summary"]
    assert "no convierte unidades" in payload["summary"]

    custom = client.get("/inventory/alerts", params={"threshold": 11})
    assert [item["name"] for item in custom.json()["alerts"]] == ["Bajo", "Justo"]

    empty = client.get("/inventory/alerts", params={"threshold": 0})
    assert empty.json()["count"] == 0
    assert "Ningún producto" in empty.json()["summary"]


def test_unknown_route_message(client):
    response = client.get("/no-existe")
    assert response.status_code == 404
    assert "ruta no existe" in response.json()["detail"]
