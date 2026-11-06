from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import agent
from agent import MOCK_DEMO_LINES, ThinkResult, ToolCall, mock_think, render_session, run_turn
from api.app import app
from safe_csv import LOG_FIELDS, read_rows
from tests.conftest import ROOT, api_request


def test_tools_have_name_description_and_typed_parameters():
    names = []
    for tool in agent.TOOLS:
        function = tool["function"]
        names.append(function["name"])
        assert function["description"].strip()
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        for spec in parameters["properties"].values():
            assert spec["type"] in {"string", "number", "integer", "boolean"}
            assert spec["description"].strip()
    assert names == ["list_inventory", "add_product", "update_stock", "get_low_stock_alerts"]
    required = {tool["function"]["name"]: tool["function"]["parameters"]["required"] for tool in agent.TOOLS}
    assert required["add_product"] == ["name", "quantity", "unit"]
    assert required["update_stock"] == ["product_id", "delta"]


def test_mock_demo_is_labeled_and_matches_the_transcript(isolate_runtime_files):
    isolate_runtime_files["products"].write_bytes((ROOT / "products.csv").read_bytes())
    client = TestClient(app)
    text = render_session(
        MOCK_DEMO_LINES,
        request=api_request(client),
        log_file=isolate_runtime_files["log"],
    )
    transcript = ROOT / "docs" / "demo-mock-transcript.txt"
    assert transcript.read_text(encoding="utf-8") == text
    assert text.startswith("Inventario de suministros\nModo: MOCK\n")
    assert "no demuestra que el modelo seleccione tools" in text
    assert "[local]\n" in text
    assert "[mock]\n" in text
    before, after = text.split("> ¿Qué productos están por agotarse?", maxsplit=1)
    assert "4 productos por debajo del umbral" in before
    assert "Leche de avena queda en 38 unidades" in before
    assert "Café arábica queda en 28 bolsas" in before
    assert "3 productos por debajo del umbral" in after
    assert "Leche de avena" not in after
    assert "Azúcar" in after
    assert "Sirope de vainilla" in after
    assert "Chocolate en polvo" in after
    rows = read_rows(isolate_runtime_files["log"], LOG_FIELDS)
    assert rows[0]["actor"] == "user"
    assert any(row["tool_call"] == "update_stock" and row["actor"] == "tool" for row in rows)
    assert any(row["tool_call"] == "get_low_stock_alerts" for row in rows)


def test_mock_session_does_not_construct_the_openai_client(monkeypatch, isolate_runtime_files):
    isolate_runtime_files["products"].write_bytes((ROOT / "products.csv").read_bytes())

    def boom(*_args, **_kwargs):
        raise AssertionError("El modo mock no debe construir el cliente OpenAI.")

    monkeypatch.setattr(agent, "OpenAI", boom)
    client = TestClient(app)
    text = render_session(
        ("alertas", "lista el inventario", "salir"),
        request=api_request(client),
        log_file=isolate_runtime_files["log"],
    )
    assert "Modo: MOCK" in text
    assert "Inventario:" in text
    assert "Leche de avena" in text


def test_help_and_alerts_are_local_commands(isolate_runtime_files):
    isolate_runtime_files["products"].write_bytes((ROOT / "products.csv").read_bytes())
    client = TestClient(app)
    calls = {"n": 0}

    def think(_messages):
        calls["n"] += 1
        return ThinkResult(content="no debería ejecutarse")

    chunks: list[str] = []
    agent.run_cli(
        iter(("ayuda", "alertas", "salir")),
        chunks.append,
        mode="live",
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        think=think,
        request=api_request(client),
        max_iterations=4,
        model="no-se-llama",
        clock=lambda: "2026-11-06T08:00:00+00:00",
    )
    text = "\n".join(chunks)
    assert calls["n"] == 0
    assert "Comando local: ayuda" in text
    assert "uvicorn api.app:app --reload" in text
    assert "Comando local: consulta directa a GET /inventory/alerts" in text
    assert "4 productos por debajo del umbral" in text
    assert "[live]" not in text


def test_unknown_mock_phrase_does_not_call_the_api(isolate_runtime_files):
    def request(*_args, **_kwargs):
        raise AssertionError("Una frase fuera de la regla local no debe llamar a la API.")

    reply = run_turn(
        "¿Qué tiempo hace?",
        [],
        mock_think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=request,
        clock=lambda: "2026-11-06T08:00:00+00:00",
    )
    assert "no entiende esa frase" in reply


def test_mock_refuses_to_convert_units(isolate_runtime_files):
    isolate_runtime_files["products"].write_bytes((ROOT / "products.csv").read_bytes())
    client = TestClient(app)
    reply = run_turn(
        "Vendimos 2 litros de café arábica",
        [],
        mock_think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        clock=lambda: "2026-11-06T08:00:00+00:00",
    )
    assert "no en litros" in reply
    assert "No he cambiado el stock" in reply
    products = {item["name"]: item for item in client.get("/inventory").json()["products"]}
    assert products["Café arábica"]["quantity"] == 40


def test_mock_registers_a_new_product_and_then_alerts(isolate_runtime_files):
    client = TestClient(app)
    reply = run_turn(
        "Registra 15 cajas de tapas y dime las alertas",
        [],
        mock_think,
        base_url="http://api.test",
        log_file=isolate_runtime_files["log"],
        request=api_request(client),
        clock=lambda: "2026-11-06T08:00:00+00:00",
    )
    assert "He registrado tapas con 15 cajas (id 1)." in reply
    # 15 no está por debajo del umbral por defecto, que es 10.
    assert "Ningún producto está por debajo del umbral" in reply
    assert "tapas" in reply
    rows = read_rows(isolate_runtime_files["log"], LOG_FIELDS)
    assert [row["tool_call"] for row in rows if row["actor"] == "tool"] == ["add_product", "get_low_stock_alerts"]


def test_main_live_without_key_exits_and_mock_help_does_not(monkeypatch, capsys, isolate_runtime_files):
    monkeypatch.setattr(agent, "load_dotenv", lambda *_args, **_kwargs: False)

    def boom(*_args, **_kwargs):
        raise AssertionError("Sin clave no debe construirse el cliente.")

    monkeypatch.setattr(agent, "OpenAI", boom)
    assert agent.main([]) == 2
    error = capsys.readouterr().err
    assert "GROQ_API_KEY" in error
    assert "sk-" not in error

    monkeypatch.setattr(agent, "iter_stdin", lambda: iter(("ayuda", "salir")))
    assert agent.main(["--mock"]) == 0
    output = capsys.readouterr().out
    assert "Modo: MOCK" in output
    assert "Comando local: ayuda" in output


def test_build_client_points_the_openai_sdk_at_groq(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(agent, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-a-secret")
    agent.build_client()
    assert captured == {
        "api_key": "test-key-not-a-secret",
        "base_url": "https://api.groq.com/openai/v1",
    }


def test_live_think_sends_history_and_tools_to_the_client():
    recorded = {}

    class Completions:
        def create(self, **kwargs):
            recorded.update(kwargs)

            class Function:
                name = "list_inventory"
                arguments = "{}"

            class Call:
                id = "call-1"
                function = Function()

            class Message:
                content = None
                tool_calls = [Call()]

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class Client:
        def __init__(self):
            self.chat = self
            self.completions = Completions()

    history = [{"role": "system", "content": "sistema"}, {"role": "user", "content": "lista"}]
    result = agent.live_think(Client(), "llama-3.3-70b-versatile", history)
    assert recorded["model"] == "llama-3.3-70b-versatile"
    assert recorded["messages"] == history
    assert recorded["tools"] == agent.TOOLS
    assert recorded["tool_choice"] == "auto"
    assert result.tool_calls[0].name == "list_inventory"
    assert result.tool_calls[0].arguments == {}


def test_live_think_hides_the_key_when_the_sdk_fails():
    class Completions:
        def create(self, **_kwargs):
            raise RuntimeError("fallo con test-key-not-a-secret en el texto")

    class Client:
        def __init__(self):
            self.chat = self
            self.completions = Completions()

    result = agent.live_think(Client(), "llama-3.3-70b-versatile", [])
    assert result.tool_calls == []
    assert "RuntimeError" in result.content
    assert "test-key-not-a-secret" not in result.content


def test_seed_catalog_and_empty_log_are_in_the_repo():
    catalog = (ROOT / "products.csv").read_text(encoding="utf-8")
    assert catalog.startswith("id,name,quantity,unit\n")
    assert "Leche de avena,8,unidades" in catalog
    assert "Café arábica,40,bolsas" in catalog
    assert (ROOT / "conversation_log.csv").read_text(encoding="utf-8") == "actor,message,tool_call,timestamp\n"


def test_source_and_dependencies_do_not_import_an_agent_framework():
    forbidden = ("langchain", "llama_index", "llamaindex", "autogen", "crewai", "semantic_kernel", "langgraph")
    sources = [ROOT / "agent.py", ROOT / "api" / "app.py", ROOT / "safe_csv.py", ROOT / "alert_format.py"]
    blob = "\n".join(path.read_text(encoding="utf-8") for path in sources).lower()
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for name in forbidden:
        assert name not in blob
        assert name not in project
