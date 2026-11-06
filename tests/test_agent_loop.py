from __future__ import annotations

import json
from datetime import datetime

from agent import ThinkResult, ToolCall, execute_tool, run_turn
from safe_csv import LOG_FIELDS, read_rows
from tests.conftest import api_request


def _fixed_clock():
    stamp = {"n": 0}

    def clock() -> str:
        stamp["n"] += 1
        return f"2026-11-06T08:00:{stamp['n']:02d}+00:00"

    return clock


def test_dispatch_uses_the_endpoint_that_matches_the_tool(client):
    client.post("/inventory", json={"name": "Azúcar", "quantity": 5, "unit": "kg"})
    seen: list[tuple] = []
    real = api_request(client)

    def request(method, url, payload=None, timeout=30.0):
        seen.append((method, url, payload))
        return real(method, url, payload, timeout)

    assert execute_tool("list_inventory", {}, base_url="http://api.test", request=request, timeout=5)["status_code"] == 200
    created = execute_tool(
        "add_product",
        {"name": "Tapas", "quantity": 15, "unit": "cajas"},
        base_url="http://api.test",
        request=request,
        timeout=5,
    )
    assert created["status_code"] == 201
    updated = execute_tool(
        "update_stock",
        {"product_id": "1", "delta": -1},
        base_url="http://api.test",
        request=request,
        timeout=5,
    )
    assert updated["status_code"] == 200
    assert updated["body"]["product"]["quantity"] == 4
    alerts = execute_tool(
        "get_low_stock_alerts",
        {"threshold": 6},
        base_url="http://api.test",
        request=request,
        timeout=5,
    )
    assert alerts["status_code"] == 200
    assert [item["name"] for item in alerts["body"]["alerts"]] == ["Azúcar"]

    methods = [(method, url.split("?")[0], payload) for method, url, payload in seen]
    assert methods[0][0:2] == ("GET", "http://api.test/inventory")
    assert methods[1] == ("POST", "http://api.test/inventory", {"name": "Tapas", "quantity": 15, "unit": "cajas"})
    assert methods[2] == ("PATCH", "http://api.test/inventory/1", {"delta": -1})
    assert methods[3][0] == "GET"
    assert methods[3][1] == "http://api.test/inventory/alerts"
    assert "threshold=6" in seen[3][1]


def test_multistep_add_then_alerts_injects_each_result(client, isolate_runtime_files):
    seen: list[list[dict]] = []

    def think(messages):
        seen.append(messages)
        tool_messages = [message for message in messages if message["role"] == "tool"]
        if len(tool_messages) == 0:
            return ThinkResult(
                tool_calls=[ToolCall("step-add", "add_product", {"name": "Tapas", "quantity": 15, "unit": "cajas"})]
            )
        if len(tool_messages) == 1:
            assert "Tapas" in tool_messages[0]["content"]
            return ThinkResult(tool_calls=[ToolCall("step-alerts", "get_low_stock_alerts", {})])
        assert "Tapas" in tool_messages[0]["content"]
        assert "threshold" in tool_messages[1]["content"]
        return ThinkResult(content="He registrado Tapas y he consultado las alertas.")

    history: list[dict] = []
    reply = run_turn(
        "Registra tapas y dime las alertas",
        history,
        think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        clock=_fixed_clock(),
    )
    assert reply == "He registrado Tapas y he consultado las alertas."
    assert len(seen) == 3
    roles = [message["role"] for message in history]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert history[3]["role"] == "tool"
    assert "Tapas" in history[3]["content"]
    assert history[5]["role"] == "tool"
    names = [item["name"] for item in client.get("/inventory").json()["products"]]
    assert names == ["Tapas"]

    rows = read_rows(isolate_runtime_files["log"], LOG_FIELDS)
    assert [(row["actor"], row["tool_call"]) for row in rows] == [
        ("user", ""),
        ("agent", "add_product"),
        ("tool", "add_product"),
        ("agent", "get_low_stock_alerts"),
        ("tool", "get_low_stock_alerts"),
        ("agent", ""),
    ]
    for row in rows:
        datetime.fromisoformat(row["timestamp"])
        assert row["actor"] in {"user", "agent", "tool"}
    assert rows[-1]["message"] == reply
    assert json.loads(rows[2]["message"])["status_code"] == 201


def test_loop_stops_when_there_are_no_tool_calls(client, isolate_runtime_files):
    def think(_messages):
        return ThinkResult(content="No hace falta tocar el stock.")

    reply = run_turn(
        "hola",
        [],
        think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        clock=_fixed_clock(),
    )
    assert reply == "No hace falta tocar el stock."
    rows = read_rows(isolate_runtime_files["log"], LOG_FIELDS)
    assert [row["actor"] for row in rows] == ["user", "agent"]
    assert rows[0]["tool_call"] == ""
    assert rows[1]["tool_call"] == ""


def test_history_stays_in_memory_for_the_session(client, isolate_runtime_files):
    history: list[dict] = []

    def think(messages):
        users = [message["content"] for message in messages if message["role"] == "user"]
        if users == ["primero"]:
            return ThinkResult(content="anotado")
        assert "primero" in users
        assert any(message["role"] == "assistant" and message["content"] == "anotado" for message in messages)
        return ThinkResult(content="sigo en la misma sesión")

    run_turn(
        "primero",
        history,
        think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        clock=_fixed_clock(),
    )
    reply = run_turn(
        "segundo",
        history,
        think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        clock=_fixed_clock(),
    )
    assert reply == "sigo en la misma sesión"
    assert [message["content"] for message in history if message["role"] == "user"] == ["primero", "segundo"]


def test_iteration_limit_stops_the_tool_loop(client, isolate_runtime_files):
    calls = {"n": 0}

    def think(messages):
        calls["n"] += 1
        if calls["n"] == 2:
            assert any(message["role"] == "tool" for message in messages)
        return ThinkResult(tool_calls=[ToolCall(f"call-{calls['n']}", "list_inventory", {})])

    reply = run_turn(
        "repite",
        [],
        think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        max_iterations=2,
        clock=_fixed_clock(),
    )
    assert calls["n"] == 2
    assert "límite de 2" in reply
    rows = read_rows(isolate_runtime_files["log"], LOG_FIELDS)
    assert rows[-1]["actor"] == "agent"
    assert rows[-1]["tool_call"] == ""
    assert rows[-1]["message"] == reply


def test_two_sessions_only_append(client, isolate_runtime_files):
    log_file = isolate_runtime_files["log"]

    def reply_with(text):
        def think(_messages):
            return ThinkResult(content=text)

        return think

    run_turn(
        "hola",
        [],
        reply_with("primera"),
        base_url="http://api.test",
        log_file=log_file,
        request=api_request(client),
        clock=_fixed_clock(),
    )
    first_bytes = log_file.read_bytes()
    run_turn(
        "otra vez",
        [],
        reply_with("segunda"),
        base_url="http://api.test",
        log_file=log_file,
        request=api_request(client),
        clock=_fixed_clock(),
    )
    assert log_file.read_bytes().startswith(first_bytes)
    rows = read_rows(log_file, LOG_FIELDS)
    assert [row["message"] for row in rows] == ["hola", "primera", "otra vez", "segunda"]
    assert log_file.read_text(encoding="utf-8").count("actor,message,tool_call,timestamp") == 1


def test_api_error_is_injected_and_the_loop_can_finish(isolate_runtime_files):
    def request(_method, _url, _payload=None, _timeout=30.0):
        return {"status_code": None, "body": {"detail": "No pude contactar con la API."}}

    def think(messages):
        if not any(message["role"] == "tool" for message in messages):
            return ThinkResult(tool_calls=[ToolCall("down", "list_inventory", {})])
        assert "No pude contactar con la API." in messages[-1]["content"]
        return ThinkResult(content="La API no está en marcha.")

    reply = run_turn(
        "lista",
        [],
        think,
        base_url="http://127.0.0.1:9",
        log_file=isolate_runtime_files["log"],
        request=request,
        timeout=0.2,
        clock=_fixed_clock(),
    )
    assert reply == "La API no está en marcha."


def test_unknown_tool_and_missing_arguments_do_not_crash(client, isolate_runtime_files):
    def think(messages):
        tool_messages = [message for message in messages if message["role"] == "tool"]
        if len(tool_messages) == 0:
            return ThinkResult(tool_calls=[ToolCall("bad", "does_not_exist", {})])
        if len(tool_messages) == 1:
            assert "no está definida" in tool_messages[0]["content"]
            return ThinkResult(tool_calls=[ToolCall("missing", "add_product", {"name": "Solo nombre"})])
        assert "Faltan argumentos" in tool_messages[1]["content"]
        return ThinkResult(content="No he podido completar el alta.")

    reply = run_turn(
        "haz algo",
        [],
        think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        clock=_fixed_clock(),
    )
    assert reply == "No he podido completar el alta."
    assert client.get("/inventory").json()["products"] == []
