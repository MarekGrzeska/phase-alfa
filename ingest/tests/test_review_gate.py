"""Bramka korekty na poziomie schematu (migracja 0004).

Testy pytają, czy więzy ODRZUCAJĄ złe dane, a nie czy kolumny istnieją —
test, który tylko wylicza kolumny, przechodzi zawsze i nie mówi nic.
"""

from __future__ import annotations

import pytest

from schema.migrate import polaczenie as adres

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.integracyjny


@pytest.fixture(scope="module")
def polaczenie():
    try:
        url = adres()
    except SystemExit as e:
        pytest.skip(f"brak konfiguracji bazy: {e}")
    try:
        with psycopg.connect(url, connect_timeout=5) as c:
            yield c
            c.rollback()
    except psycopg.OperationalError as e:
        pytest.skip(f"baza nieosiągalna: {e}")


@pytest.fixture
def conn(polaczenie):
    """Transakcja na test, cofana ZAWSZE — także po nieudanej asercji."""
    try:
        yield polaczenie
    finally:
        polaczenie.rollback()


def _zadanie(cur, url: str = "test://gate", status: str = "pending") -> int:
    cur.execute(
        "INSERT INTO document (segment, year, code, kind, kind_source, url, path) "
        "VALUES ('e8', 2025, 'OMAP', 'marking_scheme', 'suffix', %s, 'x.pdf') "
        "RETURNING id",
        (url,),
    )
    (doc_id,) = cur.fetchone()
    cur.execute(
        "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, "
        "review_status) VALUES (%s, '1', 1, 2, 'open_short', %s) RETURNING id",
        (doc_id, status),
    )
    (task_id,) = cur.fetchone()
    return task_id


def test_nowe_zadanie_czeka_na_czlowieka(conn):
    """Domyślny status to `pending`: parser produkuje kandydatów, nie korpus."""
    with conn.cursor() as cur:
        task_id = _zadanie(cur)
        cur.execute("SELECT review_status FROM task WHERE id = %s", (task_id,))
        assert cur.fetchone()[0] == "pending"


def test_wiez_odrzuca_wymyslony_status(conn):
    with conn.cursor() as cur:
        task_id = _zadanie(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("UPDATE task SET review_status = 'prawie_dobre' WHERE id = %s",
                        (task_id,))


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_korpus_nie_widzi_nierozstrzygnietych(conn, status):
    """`corpus_task` JEST definicją korpusu — czytają z niego C# i pipeline."""
    with conn.cursor() as cur:
        task_id = _zadanie(cur, status=status)
        cur.execute("SELECT count(*) FROM corpus_task WHERE id = %s", (task_id,))
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize("status", ["approved", "corrected"])
def test_korpus_widzi_rozstrzygniete(conn, status):
    with conn.cursor() as cur:
        task_id = _zadanie(cur, status=status)
        cur.execute("SELECT count(*) FROM corpus_task WHERE id = %s", (task_id,))
        assert cur.fetchone()[0] == 1


def test_dziennik_przezywa_skasowanie_zadania(conn):
    """Pomiar S8 jest wynikiem alfy i ma przeżyć przeładowanie korpusu.

    Stąd ON DELETE SET NULL, a nie CASCADE: wiersz bez zadania wciąż niesie
    czas i rodzaj decyzji, czyli wszystko, czego S8 potrzebuje.
    """
    with conn.cursor() as cur:
        task_id = _zadanie(cur, status="corrected")
        cur.execute(
            "INSERT INTO correction_event (task_id, action, started_at) "
            "VALUES (%s, 'correct', now() - interval '3 minutes') RETURNING id",
            (task_id,),
        )
        (event_id,) = cur.fetchone()

        cur.execute("DELETE FROM task WHERE id = %s", (task_id,))

        cur.execute(
            "SELECT task_id, extract(epoch FROM (finished_at - started_at)) "
            "FROM correction_event WHERE id = %s",
            (event_id,),
        )
        task_ref, seconds = cur.fetchone()
        assert task_ref is None
        assert seconds == pytest.approx(180, abs=5)


def test_dziennik_odrzuca_odwrocony_przedzial(conn):
    """Ujemny czas pracy to zegar albo formularz sprzed doby, nie pomiar."""
    with conn.cursor() as cur:
        task_id = _zadanie(cur)
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO correction_event (task_id, action, started_at, finished_at) "
                "VALUES (%s, 'approve', now(), now() - interval '1 hour')",
                (task_id,),
            )
