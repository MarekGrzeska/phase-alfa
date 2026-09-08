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
    return {"key": key, "paper": paper, "task": task, "version": version, "asset": asset,
            "criterion": criterion, "expression": expression}


# ------------------------------------------------------------- allowlista

def test_unknown_table_is_404_before_any_sql(client, seeded):
    for name in ("nope", "task;DROP TABLE task", "pg_catalog", "corpus_task"):
        assert client.get(f"/inspect/{name}").status_code == 404, name


def test_unknown_filter_is_named_not_silently_dropped(client, seeded):
    """Filtr, który nie działa, ale wygląda jakby działał, jest gorszy od błędu."""
    body = client.get("/inspect/task?nope=1").text
    assert "pominięty" in body and "nope" in body
    body = client.get("/inspect/task?number__nieznany=16").text
    assert "pominięty" in body
    assert client.get("/inspect/task?review_status=pending").status_code == 200


def test_filter_matches_exactly_by_text(client, seeded):
    body = client.get(f"/inspect/criterion?task_id={seeded['task']}").text
    assert f"/inspect/criterion/{seeded['criterion']}" in body
    assert "1 wierszy" in body
    assert "0 wierszy" in client.get("/inspect/criterion?task_id=999999").text


# ------------------------------------------------------------- filtry

def test_operators(client, con, seeded):
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, kind, "
                    "page, review_status) VALUES (%s, '17', 17, 4, 'closed', 12, 'approved')",
                    (seeded["key"],))

    def rows(query: str) -> int:
        body = client.get(f"/inspect/task?{query}").text
        return int(body.split(" wierszy")[0].rsplit(" ", 1)[-1])

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
    body = client.get("/inspect/task?max_points__gt=10").text
    assert "0 wierszy" in body


def test_bad_filter_value_is_a_sentence_not_a_500(client, seeded):
    response = client.get("/inspect/task?max_points__gt=abc")
    assert response.status_code == 200
    assert "nie pasuje do typu kolumny" in response.text


def test_filter_row_redirects_to_canonical_url(client, seeded):
    """Wiersz filtrów przysyła wartość i operator osobno; adres ma zostać kanoniczny."""
    response = client.get("/inspect/task?op.review_status=eq&review_status=pending",
                          follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/inspect/task?review_status=pending"

    response = client.get("/inspect/task?op.max_points=gte&max_points=2&op.kind=eq&kind=open_short",
                          follow_redirects=False)
    assert response.headers["location"] == "/inspect/task?max_points__gte=2&kind=open_short"

    # Puste pola pozostałych kolumn nie zostawiają po sobie filtru.
    response = client.get("/inspect/task?op.number=contains&number=&op.kind=eq&kind=open_short",
                          follow_redirects=False)
    assert response.headers["location"] == "/inspect/task?kind=open_short"

    # Operator bez wartości działa przy pustym polu — na tym polega „∅".
    response = client.get("/inspect/task?op.review_model=null&review_model=",
                          follow_redirects=False)
    assert response.headers["location"] == "/inspect/task?review_model__null="

    # Sortowanie i szerokość widoku przeżywają filtrowanie.
    response = client.get("/inspect/task?_sort=number&_dir=desc&_cols=all&op.kind=eq&kind=closed",
                          follow_redirects=False)
    assert response.headers["location"] == (
        "/inspect/task?kind=closed&_sort=number&_dir=desc&_cols=all")

    # Sam formularz bez żadnej wartości nie przekierowuje w kółko.
    assert client.get("/inspect/task?op.number=contains&number=",
                      follow_redirects=False).status_code == 303
    assert client.get("/inspect/task?number=16").status_code == 200


def test_every_submit_lands_on_a_canonical_url(client, seeded):
    """Filtrowanie chodzi po `onchange`, więc adres musi się czyścić także po ZDJĘCIU filtru.

    Bez tego wybranie „—" w ostatniej liście zostawiałoby w pasku komplet pustych
    `op.*`, a przycisk „wstecz" wracał do adresu, który niczego nie filtruje.
    """
    cleared = "op.kind=eq&kind=&op.review_status=eq&review_status="
    response = client.get(f"/inspect/task?{cleared}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/inspect/task"

    response = client.get(f"/inspect/task?_sort=number&_dir=desc&{cleared}",
                          follow_redirects=False)
    assert response.headers["location"] == "/inspect/task?_sort=number&_dir=desc"


def test_filter_row_submits_itself_without_a_button(client, seeded):
    body = client.get("/inspect/task").text
    row = body.split('<tr class="filters">')[1].split("</tr>")[0]
    # Każda kontrolka wiersza filtrów wysyła formularz sama.
    assert row.count('onchange="this.form.submit()"') == row.count("<select") + row.count("<input")
    # Przycisk zostaje wyłącznie dla przeglądarki bez JS-a.
    assert "<noscript><button>Filtruj</button></noscript>" in row


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


def test_page_size_choice_lands_in_a_cookie(client, many_tasks):
    def rows_on_page(response) -> int:
        body = response.text.split("<tbody>")[1].split("</tbody>")[0]
        return body.count('<tr>')

    assert rows_on_page(client.get("/inspect/task")) == inspector.PER_PAGE

    response = client.get("/inspect/task?_per=25", follow_redirects=False)
    assert response.status_code == 303
    # Rozmiar strony jest ustawieniem przeglądarki, więc znika z adresu.
    assert response.headers["location"] == "/inspect/task"
    assert response.cookies[inspector.PER_PAGE_COOKIE] == "25"

    # Klient trzyma ciasteczko, więc kolejne wejścia bez `_per` też mają 25.
    assert rows_on_page(client.get("/inspect/task")) == 25
    assert rows_on_page(client.get("/inspect/task?kind=closed")) == 25
    assert rows_on_page(client.get("/inspect/task?_page=2")) == 25

    client.get("/inspect/task?_per=100")
    assert rows_on_page(client.get("/inspect/task")) == 100
    client.cookies.clear()
    assert rows_on_page(client.get("/inspect/task")) == inspector.PER_PAGE


def test_page_size_outside_the_list_falls_back_to_default(client, many_tasks):
    for raw in ("7", "0", "-25", "abc", "", "999999"):
        assert inspector.per_page_or_default(raw) == inspector.PER_PAGE
    # Także wtedy, gdy ktoś podłoży bzdurę w ciasteczku.
    client.cookies.set(inspector.PER_PAGE_COOKIE, "7")
    body = client.get("/inspect/task").text.split("<tbody>")[1].split("</tbody>")[0]
    assert body.count("<tr>") == inspector.PER_PAGE
    client.cookies.clear()


def test_page_size_change_returns_to_the_first_page(client, many_tasks):
    """Przy 25 na stronie „strona 4" bywa już za końcem listy."""
    response = client.get("/inspect/task?_page=4&_per=100", follow_redirects=False)
    assert response.headers["location"] == "/inspect/task"


def test_page_count_follows_the_chosen_size(client, many_tasks):
    client.get("/inspect/task?_per=25")
    assert f"z {-(-many_tasks // 25)}" in client.get("/inspect/task").text
    client.get("/inspect/task?_per=100")
    assert f"z {-(-many_tasks // 100)}" in client.get("/inspect/task").text
    client.cookies.clear()


def test_filter_row_keeps_filters_from_hidden_columns(client, seeded):
    """Filtr po kolumnie spoza widoku jedzie w polu ukrytym, więc nie znika."""
    body = client.get("/inspect/task?position__gte=1").text
    assert 'name="position__gte" value="1"' in body


# ------------------------------------------------------- kolumny słownikowe

def test_check_constraints_become_dictionaries(con, seeded):
    """Wartości ze SCHEMATU, nie z danych: status bez ani jednego wiersza też jest legalny."""
    with con.cursor() as cur:
        sch = inspector.schema(cur)
    assert sch.enums["task"]["review_status"] == [
        "pending", "approved", "corrected", "rejected"]
    assert sch.enums["task"]["reviewed_by"] == ["human", "model"]
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


def test_dictionary_column_renders_a_select_not_an_input(client, seeded):
    body = client.get("/inspect/task").text
    cell = body.split('name="op.review_status"')[1].split("</td>")[0]
    assert '<select name="review_status"' in cell
    assert '<input name="review_status"' not in cell
    for value in ("pending", "approved", "corrected", "rejected"):
        assert f'<option value="{value}"' in cell
    # Operatory zawężone: po statusie nie szuka się fragmentu.
    assert 'value="contains"' not in body.split('name="op.review_status"')[1].split("</select>")[0]


# ------------------------------------------------------------- sortowanie

def test_sorting_changes_order_and_survives_filters(client, con, seeded):
    with con.cursor() as cur:
        cur.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, kind) "
                    "VALUES (%s, '17', 17, 4, 'closed'), (%s, '18', 18, 1, 'closed')",
                    (seeded["key"], seeded["key"]))
        cur.execute("SELECT id, max_points FROM task ORDER BY max_points")
        by_points = [r["id"] for r in cur.fetchall()]

    def ids(query: str) -> list[int]:
        body = client.get(f"/inspect/task?{query}").text
        seen, out = set(), []
        for chunk in body.split('/inspect/task/')[1:]:
            found = chunk.split('"')[0]
            if found.isdigit() and int(found) not in seen:
                seen.add(int(found))
                out.append(int(found))
        return out

    assert ids("_sort=max_points&_dir=asc") == by_points
    assert ids("_sort=max_points&_dir=desc") == by_points[::-1]
    # Sortowanie po kolumnie spoza tabeli jest ignorowane, nie wywala listy.
    assert client.get("/inspect/task?_sort=nope").status_code == 200
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
    assert client.get("/inspect/exam_form_document/1").status_code == 404
    assert client.get("/inspect/exam_form_document").status_code == 200


# ------------------------------------------------------------- nawigacja

def test_record_links_parents_and_children(client, seeded):
    body = client.get(f"/inspect/task/{seeded['task']}").text
    assert f"/inspect/document/{seeded['key']}" in body            # rodzic
    assert f"/inspect/criterion?task_id={seeded['task']}" in body   # dziecko: lista
    assert f"/inspect/criterion/{seeded['criterion']}" in body      # dziecko: wiersz
    assert f"/task/{seeded['task']}" in body                        # skok do korekty


def test_record_shows_column_sources_and_row_provenance(client, seeded):
    body = client.get(f"/inspect/task/{seeded['task']}").text
    assert "nierozstrzygnięte — poza korpusem" in body
    assert "ekran · verify" in body
    body = client.get(f"/inspect/condition_expression/{seeded['expression']}").text
    assert "konwerter odmówił: nieznany znak" in body


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
    body = client.get(f"/inspect/task/{seeded['task']}").text
    assert "Pliku nie ma w mirrorze" in body
    assert client.get(f"/inspect/document/{seeded['key']}.pdf").status_code == 404


# ------------------------------------------------------------- zdrowie

def test_health_counts_and_lists(client, seeded):
    index = client.get("/inspect").text
    assert "Zdrowie danych" in index
    assert "/inspect/health/asset_full_page" in index
    body = client.get("/inspect/health/asset_full_page").text
    assert f"/inspect/asset/{seeded['asset']}" in body
    body = client.get("/inspect/health/expression_failed").text
    assert "nieznany znak" in body
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

    body = client.get("/inspect/task?page=11").text
    assert "· 1 wierszy" in body
    assert "· 2 wierszy" in client.get("/inspect/task?page__gte=11").text

    # Puste pole `page` z wiersza filtrów nie jest już numerem strony.
    response = client.get("/inspect/asset?op.page=eq&page=")
    assert response.status_code == 200

    # Stan widoku jedzie pod nazwami z podkreślnikiem i nie miesza się z kolumną.
    body = client.get("/inspect/task?page=11&_sort=page&_dir=desc").text
    assert "· 1 wierszy" in body
    assert 'name="_sort" value="page"' in body


def test_filter_row_of_every_table_submits_cleanly(client, seeded):
    """Wysłanie pustego wiersza filtrów nie ma prawa wywrócić żadnej tabeli."""
    import re
    from urllib.parse import urlencode

    for table in ("task", "asset", "document", "task_version", "correction_event",
                  "condition_expression", "criterion", "rule", "exam_form"):
        for query in ("", "_cols=all"):
            body = client.get(f"/inspect/{table}?{query}").text
            row = body.split('<tr class="filters">')[1].split("</tr>")[0]
            fields = re.findall(r'<(?:select|input) name="([^"]+)"', row)
            sent = urlencode([(name, "") for name in fields])
            response = client.get(f"/inspect/{table}?{query}&{sent}",
                                  follow_redirects=False)
            assert response.status_code in (200, 303), f"{table} {query}: {response.status_code}"
