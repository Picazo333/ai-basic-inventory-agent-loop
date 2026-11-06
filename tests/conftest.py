from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_runtime_files(tmp_path, monkeypatch):
    products = tmp_path / "products.csv"
    log = tmp_path / "conversation_log.csv"
    monkeypatch.setenv("PRODUCTS_CSV_PATH", str(products))
    monkeypatch.setenv("CONVERSATION_LOG_PATH", str(log))
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    return {"products": products, "log": log, "root": ROOT}


@pytest.fixture
def client(isolate_runtime_files):
    from fastapi.testclient import TestClient
    from api.app import app

    return TestClient(app)


def api_request(client):
    def request_json(method, url, payload=None, timeout=30.0):
        parsed = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        response = client.request(method, parsed.path, params=params or None, json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text}
        return {"status_code": response.status_code, "body": body}

    return request_json
