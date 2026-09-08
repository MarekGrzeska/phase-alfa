"""Pętla agenta bez modelu: model skryptowany, prawdziwe narzędzia, prawdziwa baza.

Sedno M4: przerwanie na `{"confirm"}` i wznowienie po decyzji człowieka idą
przez ten sam graf, a rozmowa, wywołania i koszt lądują w bazie.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import anyio
import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("langchain")
pytest.importorskip("langchain_mcp_adapters")

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from agent import conversation, runtime  # noqa: E402

pytestmark = pytest.mark.integracyjny


class ScriptedModel(GenericFakeChatModel):
    """Model, który mówi to, co mu zapisano — z narzędziami, bo `create_agent` je wiąże."""

    def bind_tools(self, tools, **kwargs):
        return self


def scripted(*messages: AIMessage) -> ScriptedModel:
    return ScriptedModel(messages=iter(messages), disable_streaming=True)


def calling(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id,
                                              "type": "tool_call"}],
                     usage_metadata={"input_tokens": 1000, "output_tokens": 50,
                                     "total_tokens": 1050})


def saying(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata={"input_tokens": 1200, "output_tokens": 80,
                                                   "total_tokens": 1280})


def collect(events: Iterator) -> list[dict]:
    async def go():
        return [event async for event in events]

    return anyio.run(go)


@pytest.fixture(scope="module", autouse=True)
def database(fresh_database):
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = fresh_database
    try:
        yield fresh_database
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
def con(database):
    with psycopg.connect(database, autocommit=True, row_factory=dict_row) as c:
        yield c


@pytest.fixture
def task(con) -> int:
    with con.cursor() as cur:
        cur.execute("TRUNCATE document, task, exam_form, requirement, requirement_regime, "
                    "correction_event, agent_session, agent_confirmation, agent_tool_call "
                    "RESTART IDENTITY CASCADE")
        cur.execute("INSERT INTO requirement_regime (code, name, session_from) "
                    "VALUES ('pp2017', 'Podstawa 2017', '2019-01-01') RETURNING id")
        regime = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO document (segment, year, code, variants, session, kind, kind_source, "
            "url, path, pages) VALUES ('e8', 2025, 'OMAP', '100', '2025-05-01', "
            "'marking_scheme', 'suffix', 'test://key', 'nope/OMAP-100-2505-zasady.pdf', 30) "
            "RETURNING id")
        key = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO exam_form (regime_id, exam, subject, code, variant, version, session) "
            "VALUES (%s, 'e8', 'matematyka', 'OMAP', '100', 'X', '2025-05-01')", (regime,))
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, page) "
            "VALUES (%s, '16', 16, 1, 'closed', 11) RETURNING id", (key,))
        return cur.fetchone()["id"]


@pytest.fixture
def session(con, task) -> dict:
    runtime.SNAPSHOTS.clear()
    with con.cursor() as cur:
        return conversation.create_session(cur, "openai:gpt-5.6-terra", {"view": "overview"})


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


# ------------------------------------------------------------------ odczyt

def test_read_tool_turn_streams_and_persists(con, session):
    model = scripted(calling("db_health", {}, "call_1"),
                     saying("Kontrole bez problemów."))
    events = collect(runtime.run_turn(session, "co z danymi?", {"view": "overview"},
                                      chat_model=model))
    kinds = types(events)
    assert kinds[0] == "tool_call" and events[0]["name"] == "db_health"
    assert "tool_result" in kinds and "token" in kinds
    assert kinds[-2:] == ["usage", "done"] and events[-1]["state"] == "finished"
    usage = events[-2]
    assert usage["input_tokens"] == 2200 and usage["output_tokens"] == 130
    # terra: (2200 × 2 + 130 × 12) / 1e6 = 0,006
    assert usage["usd"] == pytest.approx(0.006, abs=1e-4)

    with con.cursor() as cur:
        rows = conversation.messages(cur, session["id"])
        calls = conversation.tool_calls(cur, session["id"])
    assert [r["role"] for r in rows] == ["operator", "agent", "agent"]
    assert rows[0]["content"] == "co z danymi?"
    assert rows[1]["tool_calls"][0]["name"] == "db_health"
    assert rows[2]["content"] == "Kontrole bez problemów."
    assert [c["tool"] for c in calls] == ["db_health"]
    assert calls[0]["message_id"] == rows[1]["id"] and calls[0]["is_error"] is False


def test_ui_tool_result_becomes_ui_event(session):
    model = scripted(calling("ui_navigate", {"target": {"view": "inspect"}}, "call_2"),
                     saying("Otwieram inspektor."))
    events = collect(runtime.run_turn(session, "pokaż inspektor", None, chat_model=model))
    ui = [e for e in events if e["type"] == "ui"]
    assert ui == [{"type": "ui", "action": "navigate", "url": "/inspect"}]


# ------------------------------------------------------------------ zgoda

def test_confirm_interrupts_then_resumes_after_accept(con, session, task):
    model = scripted(calling("task_decide", {"id": task, "action": "approve",
                                             "reasons": ["zgodne z kluczem"]}, "call_3"))
    events = collect(runtime.run_turn(session, "zatwierdź to zadanie", {"view": "task",
                                                                        "task_id": task},
                                      chat_model=model))
    kinds = types(events)
    assert "confirm" in kinds and events[-1]["state"] == "waiting"
    asked = next(e for e in events if e["type"] == "confirm")
    assert asked["tool"] == "task_decide" and asked["confirm"]["status"] == "pending"
    assert con.execute("SELECT review_status FROM task WHERE id = %s",
                       (task,)).fetchone()["review_status"] == "pending"
    with con.cursor() as cur:
        pending = conversation.pending_confirmations(cur, session["id"])
    assert [p["id"] for p in pending] == [asked["confirm"]["id"]]

    # Decyzję zapisuje API; tu wprost, jak zrobiłby endpoint.
    from agent import confirm
    with con.cursor() as cur:
        confirm.decide(cur, asked["confirm"]["id"], "accept")
    model = scripted(saying("Zatwierdzone."))
    events = collect(runtime.resume_turn(session, asked["confirm"]["id"], "accept",
                                         chat_model=model))
    kinds = types(events)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["is_error"] is False and '"approved"' in result["text"]
    assert events[-1]["state"] == "finished" and "token" in kinds
    state = con.execute("SELECT review_status, reviewed_by, review_model FROM task WHERE id = %s",
                        (task,)).fetchone()
    assert state == {"review_status": "approved", "reviewed_by": "agent",
                     "review_model": "openai:gpt-5.6-terra"}
    # Jedna prośba o zgodę, mimo że węzeł narzędzi wykonał się dwa razy.
    assert con.execute("SELECT count(*) AS n FROM agent_confirmation").fetchone()["n"] == 1
    with con.cursor() as cur:
        calls = conversation.tool_calls(cur, session["id"])
    assert calls[-1]["tool"] == "task_decide"
    assert calls[-1]["confirmation_id"] == asked["confirm"]["id"]


def test_reject_returns_error_to_model_and_changes_nothing(con, session, task):
    model = scripted(calling("task_decide", {"id": task, "action": "reject", "reasons": []},
                             "call_4"))
    events = collect(runtime.run_turn(session, "odrzuć", None, chat_model=model))
    asked = next(e for e in events if e["type"] == "confirm")
    from agent import confirm
    with con.cursor() as cur:
        confirm.decide(cur, asked["confirm"]["id"], "reject")
    events = collect(runtime.resume_turn(session, asked["confirm"]["id"], "reject",
                                         chat_model=scripted(saying("Rozumiem, zostawiam."))))
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["is_error"] is True and "odrzucił" in result["text"]
    assert con.execute("SELECT review_status FROM task WHERE id = %s",
                       (task,)).fetchone()["review_status"] == "pending"


def test_resume_without_interrupt_is_an_error(session):
    events = collect(runtime.resume_turn(session, 999, "accept", chat_model=scripted()))
    assert events[-1]["type"] == "error" and "nie ma czego wznawiać" in events[-1]["message"]


# ------------------------------------------------------------------ API

def test_api_streams_sse_and_restores_history(con, task, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    from correction.app import app

    runtime.SNAPSHOTS.clear()
    monkeypatch.setattr(runtime, "check_model", lambda model: None)
    monkeypatch.setattr(runtime, "chat_model_for",
                        lambda model: scripted(calling("db_migrations", {}, "call_5"),
                                               saying("Migracje w komplecie.")))
    with TestClient(app) as client:
        assert client.get("/api/agent/config").json()["models"][0]["label"] == "luna"
        assert client.post("/api/agent/sessions", json={"model": "openai:gpt-9"}).status_code == 400
        created = client.post("/api/agent/sessions",
                              json={"model": "openai:gpt-5.6-luna", "screen": {"view": "task"}})
        assert created.status_code == 200
        sid = created.json()["id"]

        foreign = client.post(f"/api/agent/sessions/{sid}/messages", json={"text": "hej"},
                              headers={"sec-fetch-site": "cross-site"})
        assert foreign.status_code == 403

        with client.stream("POST", f"/api/agent/sessions/{sid}/messages",
                           json={"text": "stan migracji?", "screen": {"view": "task",
                                                                       "task_id": task}}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = [line for line in r.iter_lines() if line.startswith("event:")]
        assert lines[0] == "event: tool_call" and lines[-1] == "event: done"

        restored = client.get(f"/api/agent/sessions/{sid}").json()
        assert [m["role"] for m in restored["messages"]] == ["operator", "agent", "agent"]
        assert restored["usage"]["turns"] == 2
        assert restored["session"]["screen"] == {"view": "task", "task_id": task}
        assert restored["session"]["title"] == "stan migracji?"
        listed = client.get("/api/agent/sessions").json()["sessions"]
        assert listed[0]["id"] == sid and listed[0]["messages"] == 3


def test_config_reports_mock_mode_without_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    cfg = runtime.config()
    assert cfg["mode"] == "mock" and "OPENAI_API_KEY" in cfg["reason"]
    assert [m["label"] for m in cfg["models"]] == ["luna", "terra", "sol"]
    assert cfg["default"] == "openai:gpt-5.6-terra"
    monkeypatch.setenv("AGENT_MODEL", "openai:gpt-5.6-luna")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    cfg = runtime.config()
    assert cfg["mode"] == "live" and cfg["default"] == "openai:gpt-5.6-luna"


def test_json_helpers():
    assert runtime.parse_json('{"a": 1}') == {"a": 1}
    assert runtime.parse_json("[1]") is None
    assert runtime.parse_json("nie json") is None
    assert json.loads(json.dumps({"x": 1})) == {"x": 1}
