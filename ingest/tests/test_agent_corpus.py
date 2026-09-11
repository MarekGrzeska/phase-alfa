"""Zapis do korpusu przez agenta: ta sama droga co człowiek, plus zgoda.

Sedno M2: narzędzie z `confirm` bez zgody NIE zmienia ani jednego wiersza,
a ze zgodą zostawia w dzienniku `actor = 'agent'`. Więzy pozostają ostre.
"""

from __future__ import annotations

import json
import os

import anyio
import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("mcp")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from agent import confirm  # noqa: E402
from agent.server import server  # noqa: E402

pytestmark = pytest.mark.integracyjny


def call(name: str, **arguments):
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(name, arguments)

    result = anyio.run(go)
    text = result.content[0].text if result.content else ""
    return (json.loads(text) if not result.isError else text), result.isError


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
def task(con) -> dict:
    """Zadanie z kompletem struktury: wersja, odpowiedź, próg → warunek → zapis, zasób."""
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
            "VALUES (%s, 'e8', 'matematyka', 'OMAP', '100', 'X', '2025-05-01') RETURNING id",
            (regime,))
        form = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, page) "
            "VALUES (%s, '20', 20, 3, 'open_short', 12) RETURNING id", (key,))
        task_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task_version (task_id, exam_form_id, content, page) "
            "VALUES (%s, %s, 'Treść zadania 20', 12) RETURNING id", (task_id, form))
        version = cur.fetchone()["id"]
        cur.execute("INSERT INTO model_answer (task_version_id, answer) VALUES (%s, '105') "
                    "RETURNING id", (version,))
        answer = cur.fetchone()["id"]
        cur.execute("INSERT INTO criterion (task_id, points, label, position) "
                    "VALUES (%s, 3, 'pełne rozwiązanie', 1) RETURNING id", (task_id,))
        criterion = cur.fetchone()["id"]
        cur.execute("INSERT INTO criterion (task_id, points, label, position) "
                    "VALUES (%s, 1, 'metoda', 2) RETURNING id", (task_id,))
        partial = cur.fetchone()["id"]
        cur.execute("INSERT INTO criterion_condition (criterion_id, description, position) "
                    "VALUES (%s, 'poprawny sposób', 1) RETURNING id", (criterion,))
        condition = cur.fetchone()["id"]
        cur.execute("INSERT INTO condition_expression (condition_id, expression, position) "
                    "VALUES (%s, 'P = 15', 1) RETURNING id", (condition,))
        expression = cur.fetchone()["id"]
        cur.execute("INSERT INTO asset (task_version_id, kind, path, page, bbox, description, "
                    "description_status) VALUES (%s, 'drawing', 'OMAP/2025/z20.png', 9, "
                    "ARRAY[0,0,595,842]::numeric[], 'trójkąt', 'auto') RETURNING id",
                    (version,))
        asset = cur.fetchone()["id"]
    return {"id": task_id, "version": version, "answer": answer, "criterion": criterion,
            "partial": partial, "condition": condition, "expression": expression,
            "asset": asset}


def status_of(con, task_id: int) -> dict:
    return con.execute("SELECT review_status, reviewed_by, review_model FROM task WHERE id = %s",
                       (task_id,)).fetchone()


def accept(con, confirmation_id: int) -> None:
    with con.cursor() as cur:
        confirm.decide(cur, confirmation_id, "accept")


# ------------------------------------------------------------------ więzy 0010

def test_schema_accepts_agent_and_rejects_other_actors(con, task):
    with con.cursor() as cur:
        cur.execute("UPDATE task SET reviewed_by = 'agent' WHERE id = %s", (task["id"],))
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("UPDATE task SET reviewed_by = 'llm' WHERE id = %s", (task["id"],))
        cur.execute("INSERT INTO correction_event (task_id, action, started_at, actor) "
                    "VALUES (%s, 'approve', now(), 'agent')", (task["id"],))
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("INSERT INTO correction_event (task_id, action, started_at, actor) "
                        "VALUES (%s, 'approve', now(), 'robot')", (task["id"],))


def test_confirmation_cannot_be_used_unless_accepted(con):
    with con.cursor() as cur:
        cur.execute("INSERT INTO agent_confirmation (tool, arguments, title) "
                    "VALUES ('x', '{}', 't') RETURNING id")
        cid = cur.fetchone()["id"]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("UPDATE agent_confirmation SET used_at = now() WHERE id = %s", (cid,))


# ------------------------------------------------------------------ odczyt

def test_task_get_returns_form_shape_with_field_names(task):
    body, failed = call("task_get", id=task["id"])
    assert not failed
    assert body["task"]["number"] == "20"
    assert [c["id"] for c in body["task"]["criteria"]] == [task["criterion"], task["partial"]]
    assert body["url"] == f"/task/{task['id']}"
    assert "criterion.<id>.points|label|description" in body["field_names"]["rows"]


def test_task_find_filters_by_scope_and_kind(task):
    body, _ = call("task_find", year=2025, kind="open_short")
    assert [t["id"] for t in body["tasks"]] == [task["id"]]
    assert body["next_pending"] == task["id"]
    body, _ = call("task_find", year=2019)
    assert body["tasks"] == [] and body["next_pending"] is None
    _, failed = call("task_find", status="done")
    assert failed


# ------------------------------------------------------------------ zapis

def test_task_save_on_pending_task_goes_straight_through(con, task):
    body, failed = call("task_save", id=task["id"],
                        fields={f"criterion.{task['criterion']}.label": "pełne"})
    assert not failed, body
    assert body["changes"]["edited"] == {"criterion": 1}
    assert con.execute("SELECT label FROM criterion WHERE id = %s",
                       (task["criterion"],)).fetchone()["label"] == "pełne"
    assert status_of(con, task["id"])["review_status"] == "pending"
    logged = con.execute("SELECT tool, arguments FROM agent_tool_call").fetchall()
    assert logged and logged[-1]["tool"] == "task_save"


def test_task_save_keeps_constraints_sharp(con, task):
    """Dwa progi z tą samą punktacją — więz UNIQUE (task_id, points) odrzuca."""
    body, failed = call("task_save", id=task["id"],
                        fields={f"criterion.{task['partial']}.points": "3"})
    assert failed and "UNIQUE" in body
    assert con.execute("SELECT points FROM criterion WHERE id = %s",
                       (task["partial"],)).fetchone()["points"] == 1
    body, failed = call("task_save", id=task["id"],
                        fields={f"criterion.{task['partial']}.points": "abc"})
    assert failed and "nie jest liczba" in body


def test_task_save_on_corpus_record_needs_human_consent(con, task):
    with con.cursor() as cur:
        cur.execute("UPDATE task SET review_status = 'approved' WHERE id = %s", (task["id"],))
    fields = {f"criterion.{task['criterion']}.label": "zmienione"}

    body, failed = call("task_save", id=task["id"], fields=fields)
    assert not failed and body["confirm"]["status"] == "pending"
    cid = body["confirm"]["id"]
    assert con.execute("SELECT label FROM criterion WHERE id = %s",
                       (task["criterion"],)).fetchone()["label"] == "pełne rozwiązanie"

    body, failed = call("task_save", id=task["id"], fields=fields, confirmation=cid)
    assert failed and "czeka na decyzję" in body

    accept(con, cid)
    body, failed = call("task_save", id=task["id"], fields={**fields, "task.number": "21"},
                        confirmation=cid)
    assert failed and "innych argumentów" in body

    body, failed = call("task_save", id=task["id"], fields=fields, confirmation=cid)
    assert not failed, body
    assert con.execute("SELECT label FROM criterion WHERE id = %s",
                       (task["criterion"],)).fetchone()["label"] == "zmienione"

    body, failed = call("task_save", id=task["id"], fields=fields, confirmation=cid)
    assert failed and "wykorzystane" in body


def test_task_decide_always_needs_consent_and_records_agent(con, task):
    body, failed = call("task_decide", id=task["id"], action="approve",
                        reasons=["rekord zgodny z kluczem"])
    assert not failed and "confirm" in body
    assert status_of(con, task["id"])["review_status"] == "pending"
    cid = body["confirm"]["id"]

    with con.cursor() as cur:
        confirm.decide(cur, cid, "reject")
    body, failed = call("task_decide", id=task["id"], action="approve",
                        reasons=["rekord zgodny z kluczem"], confirmation=cid)
    assert failed and "odrzucił" in body

    body, _ = call("task_decide", id=task["id"], action="approve",
                   reasons=["rekord zgodny z kluczem"])
    accept(con, body["confirm"]["id"])
    body, failed = call("task_decide", id=task["id"], action="approve",
                        reasons=["rekord zgodny z kluczem"],
                        confirmation=body["confirm"]["id"])
    assert not failed, body
    state = status_of(con, task["id"])
    assert state == {"review_status": "approved", "reviewed_by": "agent",
                     "review_model": "mcp:external"}
    event = con.execute("SELECT actor, action, fields_changed FROM correction_event "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    assert event["actor"] == "agent" and event["action"] == "approve"
    assert event["fields_changed"]["notes"] == ["rekord zgodny z kluczem"]


def test_task_add_row_then_save_sets_its_content(con, task):
    body, failed = call("task_add_row", id=task["id"], what="condition", parent=task["partial"])
    assert not failed, body
    new_id = body["created"]["condition"]
    body, failed = call("task_save", id=task["id"],
                        fields={f"condition.{new_id}.description": "sam wynik"})
    assert not failed
    assert con.execute("SELECT description FROM criterion_condition WHERE id = %s",
                       (new_id,)).fetchone()["description"] == "sam wynik"


def test_asset_describe_changes_status_like_the_form(con, task):
    body, failed = call("asset_describe", asset_id=task["asset"], description="trójkąt",
                        approve=True)
    assert not failed, body
    assert con.execute("SELECT description_status FROM asset WHERE id = %s",
                       (task["asset"],)).fetchone()["description_status"] == "approved"
    body, failed = call("asset_describe", asset_id=task["asset"],
                        description="trójkąt prostokątny")
    assert not failed
    assert con.execute("SELECT description_status FROM asset WHERE id = %s",
                       (task["asset"],)).fetchone()["description_status"] == "corrected"


def test_asset_frame_needs_a_paper_in_the_mirror(task):
    body, failed = call("asset_frame", asset_id=task["asset"],
                        box={"x0": 10, "top": 20, "x1": 200, "bottom": 300})
    assert failed and "zeszytu" in body


# ------------------------------------------------------------------ db_execute

def test_db_execute_changes_nothing_without_consent(con, task):
    sql = f"UPDATE task SET number = '99' WHERE id = {task['id']}"  # noqa: S608 - to JEST wejście narzędzia
    body, failed = call("db_execute", sql=sql)
    assert not failed and body["confirm"]["tool"] == "db_execute"
    assert "dotknie wierszy (próba): 1" in body["confirm"]["preview"]
    assert con.execute("SELECT number FROM task WHERE id = %s",
                       (task["id"],)).fetchone()["number"] == "20"

    accept(con, body["confirm"]["id"])
    body, failed = call("db_execute", sql=sql, confirmation=body["confirm"]["id"])
    assert not failed, body
    assert body["affected_rows"] == 1
    assert con.execute("SELECT number FROM task WHERE id = %s",
                       (task["id"],)).fetchone()["number"] == "99"


def test_db_execute_reports_bad_sql_without_asking(task):
    body, failed = call("db_execute", sql="UPDATE nope SET x = 1")
    assert failed and "nope" in body


# ------------------------------------------------------------------ API zgód

def test_global_list_refuses_a_confirmation_that_belongs_to_a_conversation(con, task):
    """Zgoda z rozmowy rozstrzygnięta z listy globalnej zawieszała tę rozmowę.

    Tamto wejście zapisuje decyzję, ale nie wznawia grafu — więc panel dostawał 400
    i tura nie miała już żadnej drogi do końca (przegląd 11.09.2026, komentarz 5).
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    from correction.app import app

    with con.cursor() as cur:
        cur.execute("INSERT INTO agent_session (model) VALUES ('openai:gpt-5.6-terra') "
                    "RETURNING id")
        session = cur.fetchone()["id"]
        cur.execute("INSERT INTO agent_confirmation (session_id, tool, arguments, title) "
                    "VALUES (%s, 'task_decide', '{}', 'z rozmowy') RETURNING id", (session,))
        owned = cur.fetchone()["id"]
    with TestClient(app) as client:
        response = client.post(f"/api/agent/confirmations/{owned}", json={"decision": "accept"})
        assert response.status_code == 409
        assert f"#{session}" in response.json()["detail"]
    assert con.execute("SELECT decision FROM agent_confirmation WHERE id = %s",
                       (owned,)).fetchone()["decision"] is None


def test_decide_or_confirm_lets_a_settled_decision_through(con, task):
    """Wznowienie ma dokończyć turę także wtedy, gdy decyzja jest już zapisana."""
    with con.cursor() as cur:
        cur.execute("INSERT INTO agent_confirmation (tool, arguments, title) "
                    "VALUES ('db_execute', '{}', 't') RETURNING id")
        cid = cur.fetchone()["id"]
        assert confirm.decide_or_confirm(cur, cid, "accept")["decision"] == "accept"
        # Druga próba z TĄ SAMĄ decyzją przechodzi — to jest cała poprawka.
        assert confirm.decide_or_confirm(cur, cid, "accept")["decision"] == "accept"
        # Z inną decyzją nie: zmiana zdania po fakcie to nie jest wznowienie.
        with pytest.raises(ValueError, match="rozstrzygnięte"):
            confirm.decide_or_confirm(cur, cid, "reject")


def test_confirmation_api_lists_and_decides(con, task):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    from correction.app import app

    body, _ = call("task_decide", id=task["id"], action="reject")
    cid = body["confirm"]["id"]
    with TestClient(app) as client:
        pending = client.get("/api/agent/confirmations").json()["pending"]
        assert [p["id"] for p in pending] == [cid]
        assert pending[0]["tool"] == "task_decide"
        foreign = client.post(f"/api/agent/confirmations/{cid}", json={"decision": "accept"},
                              headers={"sec-fetch-site": "cross-site"})
        assert foreign.status_code == 403
        done = client.post(f"/api/agent/confirmations/{cid}", json={"decision": "accept"})
        assert done.status_code == 200 and done.json()["decision"] == "accept"
        assert client.get("/api/agent/confirmations").json()["pending"] == []
        again = client.post(f"/api/agent/confirmations/{cid}", json={"decision": "reject"})
        assert again.status_code == 404
