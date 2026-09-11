"""Inspektor danych: allowlista tabel, nawigacja po kluczach obcych, źródło wiersza.

Sedno nie jest w tym, że strona się renderuje, tylko w tym, że nazwa tabeli
z adresu NIE trafia do SQL-a: nieznana kończy się 404, a filtr po nieznanej
kolumnie 400 — zanim cokolwiek dotknie bazy.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from fastapi.testclient import TestClient  # noqa: E402 - po importorskip
from psycopg.rows import dict_row  # noqa: E402

from correction import inspector  # noqa: E402

pytestmark = pytest.mark.integracyjny


@pytest.fixture(scope="module")
def client(fresh_database):
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
def seeded(con) -> dict:
    """Klucz → zadanie → próg → warunek → zapis, wersja z zasobem; plików na dysku brak."""
    with con.cursor() as cur:
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
            "INSERT INTO document (segment, year, code, variants, session, kind, kind_source, "
            "url, path, pages) VALUES ('e8', 2025, 'OMAP', '100', '2025-05-01', "
            "'paper', 'suffix', 'test://paper', 'nope/OMAP-100-2505.pdf', 20) RETURNING id")
        paper = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO exam_form (regime_id, exam, subject, code, variant, version, session) "
            "VALUES (%s, 'e8', 'matematyka', 'OMAP', '100', 'X', '2025-05-01') RETURNING id",
            (regime,))
        form = cur.fetchone()["id"]
        cur.execute("INSERT INTO exam_form_document VALUES (%s, %s, 'marking_scheme'), "
                    "(%s, %s, 'paper')", (form, key, form, paper))
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, page) "
            "VALUES (%s, '16', 16, 2, 'open_short', 11) RETURNING id", (key,))
        task = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task_version (task_id, exam_form_id, paper_id, content, page) "
            "VALUES (%s, %s, %s, 'Oblicz pole.', 9) RETURNING id", (task, form, paper))
        version = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO asset (task_version_id, kind, path, page, bbox) VALUES "
            "(%s, 'drawing', 'OMAP/2025-05-01/100/X/z16-0.png', 9, "
            "ARRAY[0,0,595,842]::numeric[]) RETURNING id", (version,))
        asset = cur.fetchone()["id"]
        cur.execute("INSERT INTO criterion (task_id, points, label, position) "
                    "VALUES (%s, 2, 'pełne', 1) RETURNING id", (task,))
        criterion = cur.fetchone()["id"]
        cur.execute("INSERT INTO criterion_condition (criterion_id, description, position) "
                    "VALUES (%s, 'poprawna metoda', 1) RETURNING id", (criterion,))
        condition = cur.fetchone()["id"]
        cur.execute("INSERT INTO condition_expression (condition_id, expression, position, "
                    "mathjson_status, mathjson_error) VALUES (%s, 'P = 2x', 1, 'failed', "
                    "'nieznany znak') RETURNING id", (condition,))
        expression = cur.fetchone()["id"]
        cur.execute("INSERT INTO rule (marking_scheme_id, kind, content, position) "
                    "VALUES (%s, 'calculator', 'Kalkulator niedozwolony.', 1) RETURNING id",
                    (key,))
        rule = cur.fetchone()["id"]
    return {"key": key, "paper": paper, "task": task, "version": version, "asset": asset,
            "criterion": criterion, "expression": expression, "rule": rule}


# Widok rysuje React, więc pytamy o DANE. Skorupa strony sprawdza tylko tyle,
# czy adres w ogóle prowadzi do istniejącej tabeli.
def _list(client, table: str, query: str = "") -> dict:
    response = client.get(f"/api/inspect/{table}" + (f"?{query}" if query else ""))
    assert response.status_code == 200, response.text[:200]
    return response.json()


# ------------------------------------------------------------- allowlista

def test_unknown_table_is_404_before_any_sql(client, seeded):
    for name in ("nope", "task;DROP TABLE task", "pg_catalog", "corpus_task"):
        assert client.get(f"/inspect/{name}").status_code == 404, name
        assert client.get(f"/api/inspect/{name}").status_code == 404, name


def test_unknown_filter_is_named_not_silently_dropped(client, seeded):
    """Filtr, który nie działa, ale wygląda jakby działał, jest gorszy od błędu."""
    errors = " ".join(_list(client, "task", "nope=1")["errors"])
    assert "pominięty" in errors and "nope" in errors
    assert "pominięty" in " ".join(_list(client, "task", "number__nieznany=16")["errors"])
    assert _list(client, "task", "review_status=pending")["errors"] == []


def test_filter_matches_exactly_by_text(client, seeded):
    body = _list(client, "criterion", f"task_id={seeded['task']}")
    assert body["total"] == 1
    assert [row["key"] for row in body["rows"]] == [seeded["criterion"]]
    assert _list(client, "criterion", "task_id=999999")["total"] == 0


# ------------------------------------------------------------- filtry

def test_operators(client, con, seeded):
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, kind, "
                    "page, review_status) VALUES (%s, '17', 17, 4, 'closed', 12, 'approved')",
                    (seeded["key"],))

    def rows(query: str) -> int:
        return _list(client, "task", query)["total"]

    assert rows("max_points__gt=2") == 1
    assert rows("max_points__gte=2") == 2
    assert rows("max_points__lt=4") == 1
    assert rows("number__contains=1") == 2
    assert rows("kind__ne=closed") == 1
    assert rows("review_status__eq=approved") == 1
    assert rows("review_model__null=") == 2
    assert rows("review_model__notnull=") == 0
    # Dwa filtry naraz łączy AND.
    assert rows("kind__ne=closed&max_points__gte=2") == 1


def test_numeric_comparison_is_not_textual(client, con, seeded):
    """'9' > '10' jest prawdą dla napisów i fałszem dla liczb — ma być fałszem."""
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, kind) "
                    "VALUES (%s, '18', 18, 9, 'open_short')", (seeded["key"],))
    assert _list(client, "task", "max_points__gt=10")["total"] == 0


def test_bad_filter_value_is_a_sentence_not_a_500(client, seeded):
    body = _list(client, "task", "max_points__gt=abc")
    assert "nie pasuje do typu kolumny" in " ".join(body["errors"])
    assert body["rows"] == []


def test_filter_row_gets_a_canonical_url_back(client, seeded):
    """Wiersz filtrów przysyła wartość i operator osobno; adres ma wrócić kanoniczny.

    Postać kanoniczną liczy serwer i odsyła w `links.canonical` — front wpisuje ją
    w pasek adresu, żeby dało się ją skopiować, a „wstecz" nie wracał do wysłanego
    formularza.
    """
    def canonical(query: str) -> str:
        return _list(client, "task", query)["links"]["canonical"]

    assert canonical("op.review_status=eq&review_status=pending") == (
        "/inspect/task?review_status=pending")
    assert canonical("op.max_points=gte&max_points=2&op.kind=eq&kind=open_short") == (
        "/inspect/task?max_points__gte=2&kind=open_short")

    # Puste pola pozostałych kolumn nie zostawiają po sobie filtru.
    assert canonical("op.number=contains&number=&op.kind=eq&kind=open_short") == (
        "/inspect/task?kind=open_short")

    # Operator bez wartości działa przy pustym polu — na tym polega „∅".
    assert canonical("op.review_model=null&review_model=") == (
        "/inspect/task?review_model__null=")

    # Sortowanie i szerokość widoku przeżywają filtrowanie.
    assert canonical("_sort=number&_dir=desc&_cols=all&op.kind=eq&kind=closed") == (
        "/inspect/task?kind=closed&_sort=number&_dir=desc&_cols=all")


def test_cleared_filter_row_leaves_a_clean_url(client, seeded):
    """Filtrowanie chodzi po zmianie pola, więc adres musi się czyścić także po ZDJĘCIU
    filtru — inaczej wybranie „—" w ostatniej liście zostawiałoby w pasku komplet
    pustych `op.*`, a „wstecz" wracał do adresu, który niczego nie filtruje."""
    cleared = "op.kind=eq&kind=&op.review_status=eq&review_status="
    assert _list(client, "task", cleared)["links"]["canonical"] == "/inspect/task"
    assert _list(client, "task", f"_sort=number&_dir=desc&{cleared}")["links"]["canonical"] == (
        "/inspect/task?_sort=number&_dir=desc")


# ------------------------------------------------------------- rozmiar strony

@pytest.fixture
def many_tasks(con, seeded) -> int:
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind) "
            "VALUES (%s, %s, %s, 1, 'closed')",
            [(seeded["key"], str(n), n) for n in range(100, 220)])
        cur.execute("SELECT count(*) AS n FROM task")
        return cur.fetchone()["n"]


def test_page_size_comes_from_the_url(client, many_tasks):
    """Rozmiar strony jest wyborem człowieka; pamięta go front, stosuje serwer."""
    assert len(_list(client, "task")["rows"]) == inspector.PER_PAGE

    chosen = _list(client, "task", "_per=25")
    assert chosen["view"]["per_page"] == 25
    assert len(chosen["rows"]) == 25
    assert len(_list(client, "task", "_per=25&kind=closed")["rows"]) == 25
    assert len(_list(client, "task", "_per=100")["rows"]) == 100


def test_page_size_outside_the_list_falls_back_to_default(client, many_tasks):
    for raw in ("7", "0", "-25", "abc", "", "999999"):
        assert inspector.per_page_or_default(raw) == inspector.PER_PAGE
    # Także wtedy, gdy ktoś podłoży bzdurę w adresie.
    assert _list(client, "task", "_per=7")["view"]["per_page"] == inspector.PER_PAGE


def test_page_size_change_returns_to_the_first_page(client, many_tasks):
    """Przy 25 na stronie „strona 4" bywa już za końcem listy."""
    links = _list(client, "task", "_page=4&_per=25")["links"]
    assert links["per"]["100"] == "/inspect/task?_per=100"


def test_page_count_follows_the_chosen_size(client, many_tasks):
    """Liczbę stron front liczy z `total` i `per_page` — obie mają być prawdziwe."""
    for per_page in (25, 100):
        body = _list(client, "task", f"_per={per_page}")
        assert body["total"] == many_tasks
        assert body["view"]["per_page"] == per_page
        assert len(body["rows"]) == min(per_page, many_tasks)


def test_filter_from_a_hidden_column_still_filters(client, seeded):
    """Filtr po kolumnie spoza widoku działa i zostaje w stanie widoku.

    Że jedzie dalej w polu ukrytym wiersza filtrów, pilnuje test frontu — tu
    chodzi o to, że serwer go widzi i stosuje.
    """
    body = _list(client, "task", "position__gte=1")
    assert [f["param"] for f in body["view"]["filters"]] == ["position__gte"]
    assert body["total"] == 1


# ------------------------------------------------------- kolumny słownikowe

def test_check_constraints_become_dictionaries(con, seeded):
    """Wartości ze SCHEMATU, nie z danych: status bez ani jednego wiersza też jest legalny."""
    with con.cursor() as cur:
        sch = inspector.schema(cur)
    assert sch.enums["task"]["review_status"] == [
        "pending", "approved", "corrected", "rejected"]
    assert sch.enums["task"]["reviewed_by"] == ["human", "model", "agent"]
    assert sch.enums["asset"]["description_status"] == [
        "none", "auto", "approved", "corrected", "manual"]
    # Więz zakresowy i międzykolumnowy słownikiem NIE jest.
    assert "max_points" not in sch.enums["task"]
    assert "finished_at" not in sch.enums.get("correction_event", {})


def test_dictionary_columns_get_a_list_others_keep_typing(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        table = sch.tables["task"]
        described = inspector.column_filters(
            table, sch.enums["task"], inspector.suggestions(cur, table),
            inspector.table_size(cur, "task"))

    status = described["review_status"]
    assert status.is_enum
    # Cały słownik ze schematu, choć w danych stoi sam `pending`.
    assert status.options == ["pending", "approved", "corrected", "rejected"]
    assert status.operators == ["eq", "ne"]
    assert status.default == "eq"

    points = described["max_points"]
    assert not points.is_enum
    assert points.operators == ["eq", "ne", "gt", "gte", "lt", "lte"]

    # Kolumna NULL-owalna dostaje dodatkowo „pusta" i „niepusta".
    assert described["review_model"].operators[-2:] == ["null", "notnull"]
    assert described["position"].operators[-2:] != ["null", "notnull"]


def test_open_ended_text_keeps_typing(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        table = sch.tables["criterion_condition"]
        described = inspector.column_filters(
            table, sch.enums.get("criterion_condition", {}),
            inspector.suggestions(cur, table), inspector.table_size(cur, "criterion_condition"))
    # Zbiór otwarty i za mało wierszy na dowód powtarzalności — zostaje wpisywanie.
    assert not described["description"].is_enum
    assert described["description"].default == "contains"


def test_long_values_do_not_become_a_dropdown(con, seeded):
    """Garść wartości to jeszcze nie słownik, jeśli każda ma pół akapitu."""
    with con.cursor() as cur:
        cur.execute("UPDATE criterion_condition SET description = %s",
                    ("x" * (inspector.ENUM_VALUE_LENGTH + 1),))
        sch = inspector.schema(cur)
        table = sch.tables["criterion_condition"]
        hints = inspector.suggestions(cur, table)
        described = inspector.column_filters(table, {}, hints, rows=100)
    assert hints["description"]  # jedna wartość, więc podpowiedź istnieje
    assert not described["description"].is_enum


def test_filter_from_url_survives_a_narrower_offer(con, seeded):
    """`?kind__contains=clo` wpisane ręcznie ma przeżyć render, a nie zgubić operator."""
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        table = sch.tables["task"]
        described = inspector.column_filters(
            table, sch.enums["task"], inspector.suggestions(cur, table),
            inspector.table_size(cur, "task"))
    widened = inspector.offer(described["kind"], inspector.Filter("kind", "contains", "clo"))
    assert widened.operators[0] == "contains"
    assert widened.options[0] == "clo"
    # Bez aktywnego filtru opis zostaje ten sam obiekt — zero kopiowania na darmo.
    assert inspector.offer(described["kind"], None) is described["kind"]


def test_dictionary_column_is_offered_as_a_list_not_typing(client, seeded):
    """Kolumna słownikowa daje wybór z listy — literówka w statusie dawałaby pustą
    listę i wyglądała jak brak danych."""
    described = _list(client, "task")["described"]["review_status"]
    assert described["is_enum"] is True
    assert described["options"] == ["pending", "approved", "corrected", "rejected"]
    # Operatory zawężone: po statusie nie szuka się fragmentu.
    assert "contains" not in described["operators"]


# ------------------------------------------------------------- sortowanie

def test_sorting_changes_order_and_survives_filters(client, con, seeded):
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, kind) "
                    "VALUES (%s, '17', 17, 4, 'closed'), (%s, '18', 18, 1, 'closed')",
                    (seeded["key"], seeded["key"]))
        cur.execute("SELECT id, max_points FROM task ORDER BY max_points")
        by_points = [r["id"] for r in cur.fetchall()]

    def ids(query: str) -> list[int]:
        return [row["key"] for row in _list(client, "task", query)["rows"]]

    assert ids("_sort=max_points&_dir=asc") == by_points
    assert ids("_sort=max_points&_dir=desc") == by_points[::-1]
    # Sortowanie po kolumnie spoza tabeli jest ignorowane, nie wywala listy.
    assert _list(client, "task", "_sort=nope")["view"]["sort"] is None
    # Filtr i sortowanie działają razem.
    assert ids("kind=closed&_sort=max_points&_dir=desc") == [
        t for t in by_points[::-1] if t != seeded["task"]]


def test_sort_link_toggles_direction_and_keeps_filters(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        table = sch.tables["task"]
    view = inspector.ListView(
        table=table, filters=[inspector.Filter("kind", "eq", "open_short")],
        sort="max_points", direction="asc", page=3)
    assert view.url(sort="max_points", page=1) == (
        "/inspect/task?kind=open_short&_sort=max_points&_dir=desc")
    assert view.url(sort="number", page=1) == "/inspect/task?kind=open_short&_sort=number&_dir=asc"
    assert view.url(page=2) == "/inspect/task?kind=open_short&_sort=max_points&_dir=asc&_page=2"
    assert view.url(drop=view.filters[0], page=1) == "/inspect/task?_sort=max_points&_dir=asc"
    assert view.arrow("max_points") == " ▲"
    assert view.arrow("number") == ""


def test_suggestions_only_for_low_cardinality_columns(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        found = inspector.suggestions(cur, sch.tables["task"])
    assert found["review_status"] == ["pending"]
    assert found["kind"] == ["open_short"]
    # `number` jest tekstem, ale nie jest słownikiem — i tak trafia, bo wartości
    # jest mało; sens ma dopiero przy pełnym korpusie, gdzie ich jest 21.
    assert "review_model" not in found  # same NULL-e


def test_composite_key_table_has_no_record_view(client, seeded):
    assert client.get("/api/inspect/exam_form_document/1").status_code == 404
    assert client.get("/api/inspect/exam_form_document").status_code == 200


# ------------------------------------------------------------- nawigacja

def test_record_links_parents_and_children(client, seeded):
    body = client.get(f"/api/inspect/task/{seeded['task']}").json()
    assert any(p["url"] == f"/inspect/document/{seeded['key']}" for p in body["parents"])
    criteria = next(c for c in body["children"] if c["table"] == "criterion")
    assert criteria["url"] == f"/inspect/criterion?task_id={seeded['task']}"
    assert [r["url"] for r in criteria["rows"]] == [f"/inspect/criterion/{seeded['criterion']}"]


def test_record_shows_column_sources_and_row_provenance(client, seeded):
    body = client.get(f"/api/inspect/task/{seeded['task']}").json()
    assert "nierozstrzygnięte — poza korpusem" in " ".join(body["row_notes"])
    assert any("ekran · verify" in column["source"] for column in body["columns"])
    expression = client.get(
        f"/api/inspect/condition_expression/{seeded['expression']}").json()
    assert "konwerter odmówił: nieznany znak" in " ".join(expression["row_notes"])


# ------------------------------------------------------------- źródło w plikach

def test_expression_inherits_key_page_of_task(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        row = inspector.get_row(cur, sch, "condition_expression", seeded["expression"])
        p = inspector.provenance(cur, "condition_expression", row)
    assert p.document_id == seeded["key"]
    assert p.page == 11
    assert p.file_exists is False


def test_asset_provenance_points_at_paper_with_bbox(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        row = inspector.get_row(cur, sch, "asset", seeded["asset"])
        p = inspector.provenance(cur, "asset", row)
    assert p.document_id == seeded["paper"]
    assert p.page == 9
    assert p.bbox == [0.0, 0.0, 595.0, 842.0]
    assert p.crop_exists is False
    assert "cała strona" in " ".join(inspector.row_provenance("asset", row))


def test_missing_file_is_named_not_hidden(client, seeded):
    """Baza wskazuje plik, którego dysk nie ma — to nie jest NULL i nie ma zniknąć."""
    body = client.get(f"/api/inspect/task/{seeded['task']}").json()
    assert body["source"]["document_id"] == seeded["key"]
    assert body["source"]["file_exists"] is False
    assert client.get(f"/inspect/document/{seeded['key']}.pdf").status_code == 404


# ------------------------------------------------------- podgląd stron PDF

def test_pdf_viewer_starts_on_the_page_of_the_record(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        task = inspector.provenance(cur, "task", inspector.get_row(
            cur, sch, "task", seeded["task"]))
        rule_like = inspector.provenance(cur, "requirement", {"id": 1})
    assert inspector.viewed_page(None, task) == 11
    # Rekord bez własnej strony (reguła, wymaganie) zaczyna od pierwszej.
    assert inspector.viewed_page(None, rule_like) == 1


def test_pdf_viewer_page_comes_from_the_url_and_is_clamped(con, seeded):
    with con.cursor() as cur:
        sch = inspector.schema(cur)
        source = inspector.provenance(cur, "task", inspector.get_row(
            cur, sch, "task", seeded["task"]))
    assert source.document_pages == 30
    assert inspector.viewed_page("3", source) == 3
    # Poza dokumentem: przycięcie do zakresu, a nie pusta ramka po literówce.
    assert inspector.viewed_page("999", source) == 30
    for raw in ("0", "-2", "abc", ""):
        assert inspector.viewed_page(raw, source) == source.page


@pytest.fixture
def mirrored(monkeypatch, tmp_path, seeded) -> dict:
    """Puste PDF-y pod ścieżkami, które trzyma baza — podgląd renderuje się naprawdę."""
    pypdf = pytest.importorskip("pypdf")
    folder = tmp_path / "nope"
    folder.mkdir()
    for name, count in (("OMAP-100-2505-zasady.pdf", 30), ("OMAP-100-2505.pdf", 20)):
        writer = pypdf.PdfWriter()
        for _ in range(count):
            writer.add_blank_page(width=595, height=842)
        with (folder / name).open("wb") as handle:
            writer.write(handle)
    monkeypatch.setenv("MIRROR_ROOT", str(tmp_path))
    return seeded


def test_pdf_viewer_starts_where_the_record_is(client, mirrored):
    """Podgląd otwiera się na stronie rekordu, a numer strony jedzie w adresie."""
    body = client.get(f"/api/inspect/task/{mirrored['task']}").json()
    assert body["pdf_page"] == 11
    assert body["source"]["document_pages"] == 30
    assert client.get(f"/api/inspect/task/{mirrored['task']}?_pdfpage=1"
                      ).json()["pdf_page"] == 1

    # Reguła nie ma własnej strony — podgląd zaczyna od pierwszej.
    assert client.get(f"/api/inspect/rule/{mirrored['rule']}").json()["pdf_page"] == 1


def test_frame_travels_with_its_page_number(client, mirrored):
    """Ramka na cudzej stronie wisiałaby w powietrzu i kłamała o położeniu zasobu.

    Serwer podaje ramkę, jej stronę i rozmiar strony; rysuje ją front — i tylko
    wtedy, gdy oglądana strona jest tą właściwą. Pilnuje tego test frontu.
    """
    body = client.get(f"/api/inspect/asset/{mirrored['asset']}?_pdfpage=9").json()
    assert body["source"]["page"] == 9
    assert body["source"]["bbox"] == [0.0, 0.0, 595.0, 842.0]
    assert body["source"]["page_size"] is not None

    other = client.get(f"/api/inspect/asset/{mirrored['asset']}?_pdfpage=3").json()
    assert other["pdf_page"] == 3
    assert other["source"]["page"] == 9


# ------------------------------------------------------------- zdrowie

def test_health_counts_and_lists(client, seeded):
    index = client.get("/api/inspect").json()
    assert any(check["key"] == "asset_full_page" for check in index["health"])

    body = client.get("/api/inspect/health/asset_full_page").json()
    assert any(cell["link"] == f"/inspect/asset/{seeded['asset']}"
               for row in body["rows"] for cell in row)

    body = client.get("/api/inspect/health/expression_failed").json()
    assert "nieznany znak" in " ".join(cell["full"] for row in body["rows"] for cell in row)

    assert client.get("/api/inspect/health/nope").status_code == 404
    assert client.get("/inspect/health/nope").status_code == 404


def test_health_python_filters_see_missing_files(con, seeded):
    with con.cursor() as cur:
        missing = inspector.run_check(cur, inspector.CHECK_BY_KEY["document_missing_file"])
        crops = inspector.run_check(cur, inspector.CHECK_BY_KEY["asset_without_crop"])
    assert {r["id"] for r in missing} == {seeded["key"], seeded["paper"]}
    assert [r["id"] for r in crops] == [seeded["asset"]]


def test_column_named_like_a_view_param_is_filterable(client, con, seeded):
    """`page` jest KOLUMNĄ w task, task_version i asset — i był nie do odfiltrowania.

    Dopóki stronicowanie jechało pod `page`, `?page=11` znaczyło „strona 11",
    a wiersz filtrów wysyłał `page=` i cała lista wracała z 422.
    """
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, "
                    "kind, page) VALUES (%s, '17', 17, 1, 'closed', 12)", (seeded["key"],))

    assert _list(client, "task", "page=11")["total"] == 1
    assert _list(client, "task", "page__gte=11")["total"] == 2

    # Puste pole `page` z wiersza filtrów nie jest już numerem strony.
    assert _list(client, "asset", "op.page=eq&page=")["view"]["page"] == 1

    # Stan widoku jedzie pod nazwami z podkreślnikiem i nie miesza się z kolumną.
    body = _list(client, "task", "page=11&_sort=page&_dir=desc")
    assert body["total"] == 1
    assert body["view"]["sort"] == "page"


def test_filter_row_of_every_table_submits_cleanly(client, seeded):
    """Wysłanie pustego wiersza filtrów nie ma prawa wywrócić żadnej tabeli."""
    from urllib.parse import urlencode

    for table in ("task", "asset", "document", "task_version", "correction_event",
                  "condition_expression", "criterion", "rule", "exam_form"):
        for query in ("", "_cols=all"):
            body = _list(client, table, query)
            # Tak wygląda pusty wiersz filtrów: dla każdej widocznej kolumny
            # operator i wartość, obie puste.
            fields = []
            for column in body["visible"]:
                offer = body["described"].get(column)
                if offer is not None:
                    fields.append((f"{body['operator_prefix']}{column}", ""))
                    fields.append((column, ""))
            sent = urlencode(fields)
            response = client.get(f"/api/inspect/{table}?{query}&{sent}")
            assert response.status_code == 200, f"{table} {query}: {response.status_code}"
