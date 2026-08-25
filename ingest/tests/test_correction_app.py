"""Ekran korekty end-to-end: formularz → zapis → status → dziennik.

Sedno G2.1 nie jest w tym, że formularz się renderuje, tylko w tym, że status
bierze się z PORÓWNANIA z bazą, a nie z deklaracji człowieka — bo na tej
różnicy stoją pomiary S6 i S8.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("fastapi")
# httpx2, nie httpx: na tym stoi TestClient w starlette 1.x i to jest w lockfile.
# Wartownik wskazujący nieużywany już pakiet pomijał CAŁY ten moduł jako jedno
# `skipped` — czyli trzynaście testów znikało z przebiegu, a wynik nadal był zielony.
pytest.importorskip("httpx2")

from fastapi.testclient import TestClient  # noqa: E402 - po importorskip
from psycopg.rows import dict_row  # noqa: E402

pytestmark = pytest.mark.integracyjny


@pytest.fixture(scope="module")
def client(fresh_database):
    """Aplikacja wpięta w świeżą bazę przez DATABASE_URL — tak, jak czyta ją runner."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = fresh_database
    try:
        from correction.app import app
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
def con(fresh_database):
    with psycopg.connect(fresh_database, autocommit=True, row_factory=dict_row) as c:
        yield c


@pytest.fixture
def task(con) -> dict:
    """Jedno zadanie z kompletem struktury: próg → warunek → zapis, wersja, wymaganie."""
    with con.cursor() as cur:
        cur.execute("TRUNCATE document, task, exam_form, requirement, "
                    "requirement_regime, correction_event RESTART IDENTITY CASCADE")
        cur.execute("INSERT INTO requirement_regime (code, name, session_from) "
                    "VALUES ('pp2017', 'Podstawa 2017', '2019-01-01') RETURNING id")
        regime = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO requirement (regime_id, kind, stage, path, content) "
            "VALUES (%s, 'specific', 'VII-VIII', 'V.3', 'oblicza pole') RETURNING id",
            (regime,),
        )
        requirement = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO document (segment, year, code, session, kind, kind_source, "
            "url, path, pages) VALUES ('e8', 2025, 'OMAP', '2025-05-01', "
            "'marking_scheme', 'suffix', 'test://app', 'OMAP-100-2505-zasady.pdf', 30) "
            "RETURNING id"
        )
        document = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO exam_form (regime_id, exam, subject, code, variant, version, "
            "session) VALUES (%s, 'e8', 'matematyka', 'OMAP', '100', 'X', '2025-05-01') "
            "RETURNING id",
            (regime,),
        )
        form = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, "
            "page) VALUES (%s, '20', 20, 3, 'open_short', 12) RETURNING id",
            (document,),
        )
        task_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO task_requirement VALUES (%s, %s)", (task_id, requirement))
        cur.execute(
            "INSERT INTO task_version (task_id, exam_form_id, content, page) "
            "VALUES (%s, %s, 'Treść zadania 20', 12) RETURNING id",
            (task_id, form),
        )
        version = cur.fetchone()["id"]
        cur.execute("INSERT INTO model_answer (task_version_id, answer) "
                    "VALUES (%s, '105') RETURNING id", (version,))
        answer = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO criterion (task_id, points, label, position) "
            "VALUES (%s, 3, 'pełne rozwiązanie', 1) RETURNING id",
            (task_id,),
        )
        criterion = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO criterion_condition (criterion_id, description, position) "
            "VALUES (%s, 'poprawny sposób obliczenia pola', 1) RETURNING id",
            (criterion,),
        )
        condition = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO condition_expression (condition_id, expression, position) "
            "VALUES (%s, 'P = 15² − 3', 1) RETURNING id",
            (condition,),
        )
        expression = cur.fetchone()["id"]
    return {"id": task_id, "version": version, "answer": answer,
            "criterion": criterion, "condition": condition,
            "expression": expression, "requirement": requirement}


def _started(minutes: int = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _post(client, task, **fields):
    return client.post(f"/task/{task['id']}",
                       data={"started_at": _started(), **fields},
                       follow_redirects=False)


def _state(con, task_id: int) -> dict:
    return con.execute(
        "SELECT review_status, reviewed_at FROM task WHERE id = %s", (task_id,)
    ).fetchone()


def _events(con) -> list[dict]:
    return con.execute(
        "SELECT action, fields_changed, extract(epoch FROM (finished_at - started_at)) "
        "AS seconds FROM correction_event ORDER BY id"
    ).fetchall()


def test_strona_glowna_pokazuje_pomiar(client, task):
    response = client.get("/")
    assert response.status_code == 200
    assert "Statystyka korekty" in response.text
    assert "parser trafił sam" in response.text


def test_formularz_pokazuje_strukture_kryteriow(client, task):
    response = client.get(f"/task/{task['id']}")
    assert response.status_code == 200
    assert "pełne rozwiązanie" in response.text
    assert "poprawny sposób obliczenia pola" in response.text
    assert "P = 15² − 3" in response.text


def test_zatwierdzenie_bez_zmian_to_trafienie_parsera(client, con, task):
    response = _post(client, task, action="approve")

    assert response.status_code == 303
    assert _state(con, task["id"])["review_status"] == "approved"
    (event,) = _events(con)
    assert event["action"] == "approve"
    assert event["fields_changed"] is None
    assert event["seconds"] == pytest.approx(120, abs=15)


def test_poprawka_daje_status_corrected_choc_przycisk_ten_sam(client, con, task):
    """Jeden przycisk, dwa stany. Rozstrzyga porównanie z bazą, nie deklaracja."""
    response = _post(client, task, action="approve",
                     **{f"criterion.{task['criterion']}.label": "pełne rozwiązanie zadania"})

    assert response.status_code == 303
    assert _state(con, task["id"])["review_status"] == "corrected"
    (event,) = _events(con)
    assert event["action"] == "correct"
    assert event["fields_changed"]["edited"] == {"criterion": 1}


def test_ta_sama_wartosc_nie_jest_zmiana(client, con, task):
    """Przepisanie pola bez zmiany treści nie ma podnosić licznika poprawek."""
    _post(client, task, action="approve",
          **{f"criterion.{task['criterion']}.label": "pełne rozwiązanie"})

    assert _state(con, task["id"])["review_status"] == "approved"


def test_usuniecie_zapisu_liczy_sie_jako_poprawka(client, con, task):
    _post(client, task, action="approve",
          **{f"delete.expression.{task['expression']}": "1"})

    assert _state(con, task["id"])["review_status"] == "corrected"
    (event,) = _events(con)
    assert event["fields_changed"]["deleted"] == {"condition_expression": 1}
    assert con.execute("SELECT count(*) AS n FROM condition_expression"
                       ).fetchone()["n"] == 0


def test_puste_pole_wymagane_zatrzymuje_zapis_w_calosci(client, con, task):
    """Walidacja leci PO skasowaniu zaznaczonych wierszy, więc bez wycofania
    transakcji zostawiłaby zadanie w połowie zapisane."""
    response = _post(
        client, task, action="approve",
        **{f"condition.{task['condition']}.description": "   ",
           f"delete.expression.{task['expression']}": "1"},
    )

    assert response.status_code == 422
    assert "nie może być puste" in response.text
    assert _state(con, task["id"])["review_status"] == "pending"
    assert con.execute("SELECT count(*) AS n FROM condition_expression"
                       ).fetchone()["n"] == 1, "kasowanie nie zostało wycofane"
    assert not _events(con)


def test_formularz_wraca_z_tym_co_czlowiek_wpisal(client, task):
    """Jedno puste pole wymagane nie ma kasować pozostałych poprawek."""
    response = _post(
        client, task, action="approve",
        **{f"condition.{task['condition']}.description": "",
           f"criterion.{task['criterion']}.label": "napisane i niezapisane"},
    )

    assert response.status_code == 422
    assert "napisane i niezapisane" in response.text


def test_wiez_unique_wraca_jako_zdanie_a_nie_stack_trace(client, con, task):
    """Więzy zostają ostre, komunikaty nie. Ten więz złapał prawdziwy błąd w sondzie."""
    con.execute("INSERT INTO criterion (task_id, points, position) VALUES (%s, 0, 2)",
                (task["id"],))

    response = _post(client, task, action="approve",
                     **{f"criterion.{task['criterion']}.points": "0"})

    assert response.status_code == 422
    assert "tę samą punktację" in response.text
    assert _state(con, task["id"])["review_status"] == "pending"


def test_podmieniony_identyfikator_nie_siega_do_cudzego_zadania(client, con, task):
    """Przynależność wiersza sprawdza SQL, a nie założenie o localhoście."""
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, "
                    "max_points, kind) SELECT marking_scheme_id, '21', 21, 2, "
                    "'open_short' FROM task WHERE id = %s RETURNING id", (task["id"],))
        other_task = cur.fetchone()["id"]
        cur.execute("INSERT INTO criterion (task_id, points, label, position) "
                    "VALUES (%s, 2, 'cudze', 1) RETURNING id", (other_task,))
        other_criterion = cur.fetchone()["id"]

    response = _post(client, task, action="approve",
                     **{f"criterion.{other_criterion}.label": "podmienione"})

    assert response.status_code == 422
    assert "nie należy do tego zadania" in response.text
    assert con.execute("SELECT label FROM criterion WHERE id = %s",
                       (other_criterion,)).fetchone()["label"] == "cudze"


def test_dodanie_progu_bierze_wolna_punktacje(client, con, task):
    """UNIQUE (task_id, points) znaczy, że nowy próg nie może mieć byle jakiej wartości."""
    response = _post(client, task, action="add:criterion")

    assert response.status_code == 303
    points = [r["points"] for r in con.execute(
        "SELECT points FROM criterion WHERE task_id = %s ORDER BY points",
        (task["id"],)).fetchall()]
    assert points == [2, 3], "nowy próg wszedł z zajętą albo wymyśloną punktacją"
    assert _state(con, task["id"])["review_status"] == "pending", \
        "dodanie wiersza nie jest rozstrzygnięciem"


def test_cofniecie_do_korekty_zeruje_znacznik(client, con, task):
    _post(client, task, action="approve")
    assert _state(con, task["id"])["reviewed_at"] is not None

    response = _post(client, task, action="reopen")

    assert response.status_code == 303
    state = _state(con, task["id"])
    assert state["review_status"] == "pending"
    assert state["reviewed_at"] is None
    assert [e["action"] for e in _events(con)] == ["approve", "reopen"]


def test_nastepne_do_korekty_prowadzi_do_zadania(client, con, task):
    response = client.get("/next", follow_redirects=False)
    assert response.headers["location"] == f"/task/{task['id']}"

    _post(client, task, action="approve")

    response = client.get("/next", follow_redirects=False)
    assert response.headers["location"] == "/", "nie ma czego korygować, a ekran wysyła w zadanie"
