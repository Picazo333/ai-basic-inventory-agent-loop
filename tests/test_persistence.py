from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_products_survive_a_new_process(tmp_path):
    csv_path = tmp_path / "products.csv"
    env = os.environ.copy()
    env["PRODUCTS_CSV_PATH"] = str(csv_path)
    env.pop("GROQ_API_KEY", None)
    code = """
import sys
from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)
if sys.argv[1] == "write":
    response = client.post("/inventory", json={"name": "Canela", "quantity": 4, "unit": "botes"})
    if response.status_code != 201:
        raise SystemExit(response.text)
else:
    response = client.get("/inventory")
    if response.status_code != 200:
        raise SystemExit(response.text)
    names = [item["name"] for item in response.json()["products"]]
    if names != ["Canela"]:
        raise SystemExit(repr(names))
print("ok")
"""
    subprocess.run([sys.executable, "-c", code, "write"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, "-c", code, "read"], cwd=ROOT, env=env, check=True)
    assert "Canela" in csv_path.read_text(encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_up(url: str, proc: subprocess.Popen, log_path: Path) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(log_path.read_text(encoding="utf-8"))
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(log_path.read_text(encoding="utf-8"))


def _start_uvicorn(port: int, csv_path: Path, log_path: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["PRODUCTS_CSV_PATH"] = str(csv_path)
    env.pop("GROQ_API_KEY", None)
    log_handle = open(log_path, "a", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def test_uvicorn_restart_keeps_products_csv(tmp_path):
    csv_path = tmp_path / "products.csv"
    log_path = tmp_path / "uvicorn.log"
    first_port = _free_port()
    first_base = f"http://127.0.0.1:{first_port}"
    first = _start_uvicorn(first_port, csv_path, log_path)
    try:
        _wait_until_up(first_base + "/inventory", first, log_path)
        payload = '{"name": "Tapas", "quantity": 15, "unit": "cajas"}'.encode()
        request = urllib.request.Request(
            first_base + "/inventory",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 201
    finally:
        first.terminate()
        first.wait(timeout=10)

    second_port = _free_port()
    second_base = f"http://127.0.0.1:{second_port}"
    second = _start_uvicorn(second_port, csv_path, log_path)
    try:
        _wait_until_up(second_base + "/inventory", second, log_path)
        with urllib.request.urlopen(second_base + "/inventory", timeout=5) as response:
            status = response.status
            body = response.read().decode("utf-8")
        assert status == 200
        assert "Tapas" in body
    finally:
        second.terminate()
        second.wait(timeout=10)
