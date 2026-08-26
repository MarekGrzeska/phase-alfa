"""Zakres pracy `mathjson.fill` — co rusza `--force` (G2.6).

Reset szedł osobnym UPDATE-em bez joina do dokumentu, więc `--force --year 2025`
czyścił status CAŁEJ tabeli, a przeliczał jeden rocznik. Reszta korpusu zostawała
ze statusem 'none' przy nienaruszonym `mathjson`, czyli z pokryciem zbitym do zera.
"""

from __future__ import annotations

import pytest

from mathjson import fill
from schema.migrate import polaczenie as database_url

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.integracyjny


@pytest.fixture(scope="module")
def connection():
    try:
        url = database_url()
    except SystemExit as e:
        pytest.skip(f"brak konfiguracji bazy: {e}")
    try:
        with psycopg.connect(url, connect_timeout=5) as con:
            yield con
            con.rollback()
    except psycopg.OperationalError as e:
        pytest.skip(f"baza nieosiągalna: {e}")


@pytest.fixture
def con(connection):
    """Transakcja na test, cofana ZAWSZE — także po nieudanej asercji."""
    try:
        yield connection
    finally:
        connection.rollback()


def make_expression(cur, year: int, expression: str, status: str) -> int:
    """Jeden zapis równoważny wraz z całą drogą do dokumentu."""
    cur.execute(
        "INSERT INTO document (segment, year, code, kind, kind_source, url, path) "
        "VALUES ('e8', %s, 'OMAP', 'marking_scheme', 'suffix', %s, 'x.pdf') "
        "RETURNING id",
        (year, f"test://scope/{year}/{expression}/{status}"),
    )
    (document_id,) = cur.fetchone()
    cur.execute(
        "INSERT INTO task (marking_scheme_id, number, position, max_points, kind) "
        "VALUES (%s, '1', 1, 2, 'open_short') RETURNING id", (document_id,))
    (task_id,) = cur.fetchone()
    cur.execute("INSERT INTO criterion (task_id, points, position) "
                "VALUES (%s, 2, 1) RETURNING id", (task_id,))
    (criterion_id,) = cur.fetchone()
    cur.execute("INSERT INTO criterion_condition (criterion_id, description, position) "
                "VALUES (%s, 'warunek', 1) RETURNING id", (criterion_id,))
    (condition_id,) = cur.fetchone()
    cur.execute(
        "INSERT INTO condition_expression "
        "(condition_id, expression, position, mathjson, mathjson_status) "
        "VALUES (%s, %s, 1, '[\"Add\", 1, 1]'::jsonb, %s) RETURNING id",
        (condition_id, expression, status),
    )
    (expression_id,) = cur.fetchone()
    return expression_id


def state_of(cur, expression_id: int) -> tuple:
    cur.execute("SELECT mathjson_status, mathjson IS NOT NULL "
                "FROM condition_expression WHERE id = %s", (expression_id,))
    return cur.fetchone()


def test_force_with_a_year_leaves_other_years_alone(con, monkeypatch):
    monkeypatch.setattr(fill, "run_converter", lambda records: {})
    with con.cursor() as cur:
        other = make_expression(cur, 2024, "P=1/2", "auto")
        mine = make_expression(cur, 2025, "P=1/2", "auto")

        fill.fill(con, year=2025, force=True)

        assert state_of(cur, other) == ("auto", True), "2024 był poza zakresem"
        assert state_of(cur, mine)[0] == "failed", "2025 miał być przeliczony"


def test_force_does_not_undo_human_work(con, monkeypatch):
    monkeypatch.setattr(fill, "run_converter", lambda records: {})
    with con.cursor() as cur:
        approved = make_expression(cur, 2025, "P=1/2", "approved")

        fill.fill(con, year=2025, force=True)

        assert state_of(cur, approved) == ("approved", True)


def test_without_force_finished_expressions_stay(con, monkeypatch):
    monkeypatch.setattr(fill, "run_converter", lambda records: {})
    with con.cursor() as cur:
        done = make_expression(cur, 2025, "P=1/2", "auto")
        waiting = make_expression(cur, 2025, "zapisanie P=15 AECF", "none")

        fill.fill(con, year=2025, force=False)

        assert state_of(cur, done) == ("auto", True)
        assert state_of(cur, waiting)[0] == "failed"


def test_a_refusal_takes_the_stale_mathjson_with_it(con, monkeypatch):
    """MathJSON obok stanu `failed` byłby wynikiem, którego nikt nie potwierdził,
    a raport pokrycia liczy po statusie."""
    monkeypatch.setattr(fill, "run_converter", lambda records: {})
    with con.cursor() as cur:
        expression = make_expression(cur, 2025, "zapisanie P=15 AECF", "auto")

        fill.fill(con, year=2025, force=True)

        assert state_of(cur, expression) == ("failed", False)
