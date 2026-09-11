"""Serwer MCP od strony klienta: rejestr narzędzi, odczyt bazy, montaż pod `/mcp`.

Klient in-memory z SDK gada z tym samym obiektem serwera, który obsługuje stdio
i `/mcp` — więc to, co przechodzi tutaj, przechodzi w Claude Code.
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

from agent.server import server  # noqa: E402

pytestmark = pytest.mark.integracyjny

EXPECTED_TOOLS = {
    "db_schema", "db_query", "inspect_list", "inspect_record", "db_health", "db_migrations",
    "docs_search", "docs_read", "docs_list", "code_search", "code_read",
    "explain_column", "explain_check", "project_status", "report_list", "report_read",
    "ui_navigate", "ui_focus", "ui_open_pdf", "ui_views",
}


def call(name: str, **arguments):
    """Jedno wywołanie narzędzia przez protokół — z JSON-em w środku i flagą błędu."""
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
def seeded(database) -> dict:
    with psycopg.connect(database, autocommit=True, row_factory=dict_row) as con, \
            con.cursor() as cur:
        cur.execute("TRUNCATE document, task, exam_form, requirement, requirement_regime, "
                    "correction_event RESTART IDENTITY CASCADE")
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
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, page) "
            "VALUES (%s, '16', 16, 2, 'open_short', 11) RETURNING id", (key,))
        task = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, page) "
            "VALUES (%s, '17', 17, 1, 'closed', 12) RETURNING id", (key,))
        closed = cur.fetchone()["id"]
        cur.execute("INSERT INTO criterion (task_id, points, label, position) "
                    "VALUES (%s, 2, 'pełne', 1) RETURNING id", (task,))
        criterion = cur.fetchone()["id"]
    return {"key": key, "task": task, "closed": closed, "criterion": criterion}


# ------------------------------------------------------------------ rejestr

def test_server_exposes_the_planned_tools():
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return {t.name: t for t in (await session.list_tools()).tools}

    tools = anyio.run(go)
    assert set(tools) >= EXPECTED_TOOLS
    # Każde narzędzie z M1 jest tylko do odczytu i mówi to klientowi.
    for name in EXPECTED_TOOLS:
        assert tools[name].annotations and tools[name].annotations.readOnlyHint, name
        assert tools[name].description, name


# ------------------------------------------------------------------ baza

def test_db_query_is_read_only_and_says_so(seeded):
    body, failed = call("db_query", sql="UPDATE task SET review_status = 'approved'")
    # Sedno to SKUTEK: ani jeden wiersz się nie zmienił. Komunikat ma odesłać
    # do narzędzi, którymi zapis jest w ogóle możliwy.
    assert failed and "task_*" in body and "db_execute" in body
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        assert con.execute("SELECT count(*) FROM task WHERE review_status = 'approved'") \
            .fetchone()[0] == 0


def test_db_query_returns_rows_and_marks_truncation(seeded):
    body, failed = call("db_query", sql="SELECT id, number FROM task ORDER BY id", limit=1)
    assert not failed
    assert body["columns"] == ["id", "number"]
    assert body["rows"] == [[seeded["task"], "16"]]
    assert body["truncated"] is True and "ucięty" in body["hint"]


def test_db_query_runs_as_a_role_without_superuser(seeded):
    """Odczyt agenta chodzi na roli z migracji 0011 — bez uprawnień superusera.

    `READ ONLY` zatrzymuje zapis do bazy, ale nie zatrzymuje konstrukcji, które
    zapisem nie są: `COPY … TO PROGRAM` uruchamiał program w kontenerze bazy,
    a `pg_read_file()` czytał dysk serwera (przegląd 11.09.2026, komentarz 1).
    """
    body, failed = call("db_query", sql="SELECT current_user AS u, "
                                        "(SELECT usesuper FROM pg_user WHERE usename = "
                                        "current_user) AS s")
    assert not failed, body
    assert body["rows"] == [["klucz_agent", False]], body


def test_db_query_cannot_reach_the_filesystem_or_run_programs(seeded):
    for sql in ("SELECT pg_read_file('/etc/passwd')",
                "COPY (SELECT 1) TO PROGRAM 'touch /tmp/agent-test-proof'",
                "CREATE TEMP TABLE x AS SELECT 1",
                "SET statement_timeout = 0; SELECT 1"):
        body, failed = call("db_query", sql=sql)
        assert failed, f"{sql} PRZESZLO: {body}"


def test_db_query_multiple_statements_still_cannot_write(seeded):
    _, failed = call("db_query", sql="SELECT 1; DELETE FROM criterion")
    assert failed
    with psycopg.connect(os.environ["DATABASE_URL"]) as con:
        assert con.execute("SELECT count(*) FROM criterion").fetchone()[0] == 1


def test_db_schema_names_who_writes_each_column(seeded):
    body, failed = call("db_schema", table="criterion")
    assert not failed
    points = next(c for c in body["columns"] if c["name"] == "points")
    assert points["written_by"] == "parser · ekran"
    task_id = next(c for c in body["columns"] if c["name"] == "task_id")
    assert task_id["references"] == "task.id"
    body, failed = call("db_schema", table="nope")
    assert failed and "nie ma takiej tabeli" in body


def test_inspect_list_applies_filters_and_names_rejected_ones(seeded):
    body, failed = call("inspect_list", table="task",
                        filters={"kind": "closed", "nope": "1"}, per_page=10)
    assert not failed
    assert [r["id"] for r in body["rows"]] == [seeded["closed"]]
    assert body["rejected"] == ["nope"]
    assert body["url"] == "/inspect/task?kind=closed"


def test_inspect_record_carries_provenance(seeded):
    body, failed = call("inspect_record", table="criterion", id=seeded["criterion"])
    assert not failed
    assert body["row"]["points"] == 2
    assert any(p["table"] == "task" for p in body["parents"])
    assert body["source"]["page"] == 11 and body["source"]["file_exists"] is False


def test_db_health_counts_then_lists(seeded):
    body, _ = call("db_health")
    by_key = {c["key"]: c for c in body["checks"]}
    assert by_key["closed_without_answer"]["count"] == 1
    body, _ = call("db_health", key="closed_without_answer")
    assert [r["id"] for r in body["rows"]] == [seeded["closed"]]
    assert body["url"] == "/inspect/health/closed_without_answer"


def test_db_migrations_and_project_status_agree(seeded):
    migrations, _ = call("db_migrations")
    assert migrations["applied"] == migrations["total"] > 0
    status, failed = call("project_status")
    assert not failed
    assert status["database"]["migrations"]["applied"] == migrations["total"]
    assert status["database"]["status"]["counts"]["pending"] == 2
    assert "OPENAI_API_KEY" in status["environment"]["secrets_present"]
    assert not any(v for k, v in status["environment"]["settings"].items() if "KEY" in k)


# ------------------------------------------------------------------ nawigacja

def test_ui_tools_return_ui_events_not_side_effects():
    body, _ = call("ui_navigate", target={"view": "health", "key": "asset_full_page"})
    assert body["ui"] == {"action": "navigate", "url": "/inspect/health/asset_full_page"}
    body, _ = call("ui_focus", field="criterion.12.points")
    assert body["ui"] == {"action": "focus", "name": "criterion.12.points"}
    body, failed = call("ui_focus", field="<script>")
    assert failed


def test_navigation_never_leaves_the_app_for_a_raw_file():
    """„Przejdź na stronę 16" ma zostawić korektora w narzędziu, nie w gołym PNG."""
    body, failed = call("ui_navigate",
                        target={"view": "document_page", "document_id": 54, "page": 16})
    assert not failed
    assert body["url"] == "/inspect/document/54?_pdfpage=16"
    assert body["target"] == {"view": "inspect_record", "table": "document", "id": 54,
                              "pdf_page": 16}
    assert "surowy plik" in body["note"]

    body, _ = call("ui_navigate", target={"view": "document_pdf", "document_id": 54})
    assert body["url"] == "/inspect/document/54"

    # Plik w nowej karcie zostaje osobnym narzędziem i dalej wskazuje plik.
    body, _ = call("ui_open_pdf", document_id=54, page=16)
    assert body["ui"] == {"action": "open", "url": "/inspect/document/54.pdf#page=16"}

    # Widoki, które MAJĄ podgląd strony w środku ekranu, zostają bez zmian.
    body, _ = call("ui_navigate", target={"view": "task", "id": 7, "page": 16})
    assert body["url"] == "/task/7?page=16" and "note" not in body

    body, failed = call("ui_navigate", target={"view": "document_page", "page": 16})
    assert failed and "document_id" in body


def test_ui_views_says_which_targets_are_not_for_navigation():
    body, _ = call("ui_views")
    assert body["not_for_navigate"] == ["document_page", "document_pdf"]
    assert "pdf_page" in body["page_hint"]


# ------------------------------------------------------------------ /mcp

def test_mcp_is_served_at_slash_mcp_without_redirect(seeded):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    from correction.app import app

    headers = {"Host": "127.0.0.1:8600", "Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}}}
    with TestClient(app) as client:
        response = client.post("/mcp", headers=headers, json=init, follow_redirects=False)
        assert response.status_code == 200, response.text[:200]
        session = response.headers["mcp-session-id"]
        client.post("/mcp", headers={**headers, "mcp-session-id": session},
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed = client.post("/mcp", headers={**headers, "mcp-session-id": session},
                             json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert {t["name"] for t in listed.json()["result"]["tools"]} >= EXPECTED_TOOLS
        # Ochrona przed DNS rebinding: strona z obcego hosta nie dostaje narzędzi.
        foreign = client.post("/mcp", headers={**headers, "Host": "evil.example"}, json=init,
                              follow_redirects=False)
        assert foreign.status_code == 421
