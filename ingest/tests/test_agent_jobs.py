"""Akcje ingestu jako narzędzia: katalog → narzędzia, zgoda dla płatnych, przebieg w tle."""

from __future__ import annotations

import json
import os
import shutil
import sys

import anyio
import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("mcp")

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from agent import jobs  # noqa: E402
from agent.server import server  # noqa: E402
from agent.tools import ingest as ingest_tools  # noqa: E402
from cli import app as catalog  # noqa: E402

pytestmark = pytest.mark.integracyjny


def call(name: str, **arguments):
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool(name, arguments)

    result = anyio.run(go)
    text = result.content[0].text if result.content else ""
    return (json.loads(text) if not result.isError else text), result.isError


def listed():
    async def go():
        async with create_connected_server_and_client_session(server) as session:
            return {t.name: t for t in (await session.list_tools()).tools}

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


# ------------------------------------------------------------------ katalog

def test_every_catalog_action_is_a_tool_except_foreground():
    tools = listed()
    for group in catalog.CATALOG:
        for action in group.actions:
            name = ingest_tools.tool_name(action)
            if action.foreground:
                assert name not in tools, f"{name}: serwer nie uruchamia serwera"
                continue
            assert name in tools, name
            schema = tools[name].inputSchema["properties"]
            for param in action.params:
                assert ingest_tools.param_name(param) in schema, f"{name}: {param.flag}"
            assert "confirmation" in schema
            assert tools[name].meta["confirm"] == (action.paid or action.destructive)


def test_answers_follow_menu_rules():
    action = catalog.actions()["verify"]
    answers = ingest_tools.answers_of(action, {"year": "2025", "apply": True, "limit": "3"})
    assert catalog.build_args(action, answers) == ["--year", "2025", "--limit", "3", "--apply"]
    with pytest.raises(ValueError, match="spoza listy"):
        ingest_tools.answers_of(action, {"year": "1999"})
    with pytest.raises(ValueError, match="nie liczba"):
        ingest_tools.answers_of(action, {"limit": "trzy"})


# ------------------------------------------------------------------ zgoda

def test_paid_action_asks_before_starting_anything(con):
    body, failed = call("ingest_verify", year="2025", variant="100", apply=True)
    assert not failed and body["confirm"]["tool"] == "ingest_verify"
    assert "dry-run" in body["confirm"]["preview"]
    assert 'task verify -- --year 2025 --variant 100 --apply' in body["confirm"]["preview"]
    assert con.execute("SELECT count(*) AS n FROM agent_job").fetchone()["n"] == 0


def test_destructive_action_asks_too(con):
    body, failed = call("ingest_db_reset")
    assert not failed and "kasujący" in body["confirm"]["preview"]


# ------------------------------------------------------------------ przebieg

@pytest.mark.skipif(shutil.which("task") is None, reason="brak go-task w PATH")
def test_free_action_runs_in_background_and_finishes(con):
    body, failed = call("ingest_migrate_status")
    assert not failed, body
    job = body["job"]
    assert job["state"] in ("running", "finished")
    process = jobs.PROCESSES.get(job["id"])
    if process is not None:
        process.wait(timeout=120)
    done, _ = call("job_status", id=job["id"])
    assert done["state"] == "finished" and done["exit_code"] == 0, done
    log, _ = call("job_log", id=job["id"], tail=5)
    assert "zastosowanych" in log["text"]
    listing, _ = call("job_list")
    assert listing["jobs"][0]["id"] == job["id"]


def test_cancel_stops_a_running_process(con):
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    with con.cursor() as cur:
        job = jobs.start(cur, "sleep", command)
    assert job["state"] == "running"
    with con.cursor() as cur:
        stopped = jobs.cancel(cur, job["id"])
    assert stopped["state"] == "failed" and stopped["exit_code"] != 0
    with con.cursor() as cur, pytest.raises(ValueError, match="już się skończył"):
        jobs.cancel(cur, job["id"])


def test_job_started_before_restart_is_unknown_not_finished(con):
    with con.cursor() as cur:
        cur.execute("INSERT INTO agent_job (task, command, pid, log_path) "
                    "VALUES ('ghost', 'task ghost', 1, 'data/reports/jobs/none.log') RETURNING id")
        ghost = cur.fetchone()["id"]
        row = jobs.status(cur, ghost)
    assert row["state"] == "unknown" and "restartem" in row["note"]
