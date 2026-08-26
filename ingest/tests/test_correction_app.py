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
            "INSERT INTO document (segment, year, code, variants, session, kind, "
            "kind_source, url, path, pages) VALUES ('e8', 2025, 'OMAP', '100', "
            "'2025-05-01', 'marking_scheme', 'suffix', 'test://app', "
            "'OMAP-100-2505-zasady.pdf', 30) RETURNING id"
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


def _full(task, **overrides) -> dict:
    """Formularz taki, jaki wysyła PRZEGLĄDARKA: komplet pól, nie wycinek.

    Testy postujące wybrane pola przechodziły na kodzie, który nie umiał
    obsłużyć pełnego formularza — a pełny jest jedynym, jaki naprawdę
    przychodzi. Wartości są tu te same, co w fixture, więc domyślnie
    ten formularz NIE JEST zmianą.
    """
    fields = {
        "task.number": "20",
        "task.max_points": "3",
        "task.kind": "open_short",
        f"version.{task['version']}.content": "Treść zadania 20",
        f"answer.{task['answer']}.answer": "105",
        f"criterion.{task['criterion']}.points": "3",
        f"criterion.{task['criterion']}.label": "pełne rozwiązanie",
        # W bazie NULL — szablon renderuje puste pole i takie wraca w POST-cie.
        f"criterion.{task['criterion']}.description": "",
        f"condition.{task['condition']}.description": "poprawny sposób obliczenia pola",
        f"expression.{task['expression']}.expression": "P = 15² − 3",
        "add_requirement": "",
    }
    fields.update(overrides)
    return fields


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


def test_pelny_formularz_bez_zmian_to_trafienie_parsera(client, con, task):
    """Pusty opis progu jest w schemacie NULL-owalny i parser zostawia go pusty
    przy każdym progu z wypunktowanymi warunkami.

    Wymagalność liczona po samej NAZWIE kolumny myliła go z `description`
    w `criterion_condition`, które NOT NULL jest — i takie zadanie nie dawało
    się zatwierdzić nigdy, bo przeglądarka zawsze przysyła to pole puste.
    """
    response = _post(client, task, action="approve", **_full(task))

    assert response.status_code == 303, response.text[:400]
    assert _state(con, task["id"])["review_status"] == "approved"


def test_usuniecie_progu_zabiera_jego_warunki_i_zapisy(client, con, task):
    """Kaskada usuwa dzieci, a formularz nadal je przysyła — walidacja nie ma
    prawa uznać ich za cudze, bo wtedy usunięcie progu nie udaje się nigdy."""
    response = _post(client, task, action="approve",
                     **_full(task, **{f"delete.criterion.{task['criterion']}": "1"}))

    assert response.status_code == 303, response.text[:400]
    assert _state(con, task["id"])["review_status"] == "corrected"
    assert con.execute("SELECT count(*) AS n FROM criterion").fetchone()["n"] == 0
    assert con.execute("SELECT count(*) AS n FROM criterion_condition"
                       ).fetchone()["n"] == 0
    assert con.execute("SELECT count(*) AS n FROM condition_expression"
                       ).fetchone()["n"] == 0


@pytest.mark.parametrize("query", ["", "?status=&year=&code=", "?status=pending"])
def test_wlasny_formularz_filtrow_nie_wywraca_strony(client, task, query):
    """Opcja „wszystkie" wysyła pustą wartość — i strona ma to przyjąć."""
    assert client.get(f"/{query}").status_code == 200


def test_poprawka_sprzed_dolozenia_wiersza_nie_znika_z_pomiaru(client, con, task):
    """Poprawka zapisana przed dołożeniem progu zostaje w rekordzie na zawsze,
    więc nie ma prawa zniknąć ze statystyki trafień parsera."""
    added = _post(client, task, action="add:criterion",
                  **_full(task, **{f"criterion.{task['criterion']}.label": "inna"}))
    assert added.status_code == 303
    assert "edited_before=1" in added.headers["location"]

    # Druga runda: nic nowego nie zmieniamy, tylko zatwierdzamy.
    response = client.post(
        f"/task/{task['id']}",
        data={"started_at": _started(), "action": "approve", "edited_before": "1"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert _state(con, task["id"])["review_status"] == "corrected"


def test_zatwierdzenie_po_cofnieciu_pamieta_dawna_poprawke(client, con, task):
    """Rekord raz poprawiony ręcznie nie staje się trafieniem parsera przez to,
    że ktoś cofnął go do korekty i zatwierdził ponownie."""
    _post(client, task, action="approve",
          **_full(task, **{f"criterion.{task['criterion']}.label": "poprawiona"}))
    assert _state(con, task["id"])["review_status"] == "corrected"

    _post(client, task, action="reopen")
    _post(client, task, action="approve")

    assert _state(con, task["id"])["review_status"] == "corrected"


def test_punktacja_poza_zakresem_typu_wraca_jako_komunikat(client, con, task):
    """Smallint odrzuca 99999 klasą błędu 22, nie 23 — bez tej gałęzi cały
    formularz przepadał z odpowiedzią 500."""
    response = _post(client, task, action="approve",
                     **_full(task, **{f"criterion.{task['criterion']}.points": "99999"}))

    assert response.status_code == 422
    assert "za duża" in response.text
    assert _state(con, task["id"])["review_status"] == "pending"


def test_zdublowany_numer_zadania_wskazuje_wlasciwa_tabele(client, con, task):
    """Jeden komunikat na każdy UNIQUE kierowałby tu do kryteriów."""
    con.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, "
                "kind) SELECT marking_scheme_id, '21', 21, 2, 'open_short' FROM task "
                "WHERE id = %s", (task["id"],))

    response = _post(client, task, action="approve",
                     **_full(task, **{"task.number": "21"}))

    assert response.status_code == 422
    assert "zadanie o takim numerze" in response.text


def test_status_klucza_idzie_za_stanem_zadan(client, con, task):
    """`document.ingest_status` był obietnicą planu, której kod nie spełniał —
    kolumna stała na `new` niezależnie od tego, ile zadań przeszło przez ekran."""
    def status():
        return con.execute("SELECT ingest_status AS s FROM document "
                           "WHERE url = 'test://app'").fetchone()["s"]

    assert status() == "new"

    # Klucz ma dwa zadania: jedno rozstrzygnięte, drugie czeka.
    con.execute("INSERT INTO task (marking_scheme_id, number, position, max_points, "
                "kind) SELECT marking_scheme_id, '21', 21, 2, 'open_short' FROM task "
                "WHERE id = %s", (task["id"],))
    _post(client, task, action="approve", **_full(task))
    assert status() == "parsed", "klucz z zadaniem w kolejce nie jest domknięty"

    con.execute("UPDATE task SET review_status = 'approved' WHERE number = '21'")
    _post(client, task, action="reopen")
    _post(client, task, action="approve", **_full(task))
    assert status() == "approved"


def test_odrzucenie_wszystkiego_daje_klucz_odrzucony(client, con, task):
    _post(client, task, action="reject", **_full(task))
    assert con.execute("SELECT ingest_status AS s FROM document "
                       "WHERE url = 'test://app'").fetchone()["s"] == "rejected"


def test_wersji_zadania_nie_da_sie_skasowac_formularzem(client, con, task):
    """Kasowanie wersji pociąga kaskadą odpowiedzi wzorcowe i wycinki graficzne,
    a ekran tego nie oferuje — pole doklejone ręcznie ma być zignorowane."""
    response = _post(client, task, action="approve",
                     **_full(task, **{f"delete.version.{task['version']}": "1"}))

    assert response.status_code == 303
    assert con.execute("SELECT count(*) AS n FROM task_version").fetchone()["n"] == 1
    # Zignorowane pole nie jest zmiana, wiec status ma zostac trafieniem parsera.
    assert _state(con, task["id"])["review_status"] == "approved"


def test_zadanie_z_cudzej_strony_nie_zmienia_korpusu(client, con, task):
    """Ekran nie ma uwierzytelnienia, bo stoi na localhoście — ale to nie znaczy,
    że tylko my możemy do niego wysłać formularz."""
    response = client.post(f"/task/{task['id']}",
                           data={"started_at": _started(), "action": "approve"},
                           headers={"sec-fetch-site": "cross-site"},
                           follow_redirects=False)

    assert response.status_code == 403
    assert _state(con, task["id"])["review_status"] == "pending"


def test_nastepne_do_korekty_prowadzi_do_zadania(client, con, task):
    response = client.get("/next", follow_redirects=False)
    assert response.headers["location"] == f"/task/{task['id']}"

    _post(client, task, action="approve")

    response = client.get("/next", follow_redirects=False)
    assert response.headers["location"] == "/", "nie ma czego korygować, a ekran wysyła w zadanie"


@pytest.fixture
def klucz_z_innego_rocznika(con, task) -> int:
    """Zadanie z innego rocznika i wariantu — wcześniejsze w kolejności arkuszy."""
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO document (segment, year, code, variants, session, kind, "
            "kind_source, url, path, pages) VALUES ('e8', 2019, 'OMAP', '700', "
            "'2019-04-01', 'marking_scheme', 'suffix', 'test://obok', "
            "'OMAP-700-1904-zasady.pdf', 20) RETURNING id"
        )
        document = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, "
            "page) VALUES (%s, '1', 1, 1, 'closed', 3) RETURNING id",
            (document,),
        )
        return cur.fetchone()["id"]


def test_nastepne_do_korekty_zostaje_w_zakresie(client, task, klucz_z_innego_rocznika):
    """Pilot G2.2 pracuje na jednym roczniku, a w bazie leży osiem.

    Bez zakresu „następne do korekty" wyprowadza korektora do najstarszego
    czekającego klucza — czyli pilot kończy się na pierwszym zadaniu.
    """
    bez_zakresu = client.get("/next", follow_redirects=False)
    assert bez_zakresu.headers["location"] == f"/task/{klucz_z_innego_rocznika}"

    w_zakresie = client.get("/next?year=2025&variant=100", follow_redirects=False)
    assert w_zakresie.headers["location"] == f"/task/{task['id']}?year=2025&variant=100"


def test_zapis_nie_gubi_zakresu(client, con, task):
    """Zakres przeżywa POST: rozstrzygnięcie wraca do `/next` TEGO SAMEGO rocznika."""
    response = _post(client, task, action="approve", year="2025", variant="100",
                     **_full(task))

    assert response.status_code == 303
    assert response.headers["location"] == "/next?year=2025&variant=100"


def test_lista_filtruje_po_wariancie(client, task, klucz_z_innego_rocznika):
    """Adresy porównujemy ZE ZNAKIEM ZAPYTANIA, bo `/task/1` jest podciągiem `/task/12`.

    Bez domknięcia numeru test zaczyna kłamać, gdy tylko fixture urośnie
    do dwucyfrowych identyfikatorów.
    """
    tylko_700 = client.get("/?variant=700")
    assert f"/task/{klucz_z_innego_rocznika}?" in tylko_700.text
    assert f"/task/{task['id']}?" not in tylko_700.text

    tylko_100 = client.get("/?variant=100")
    assert f"/task/{task['id']}?" in tylko_100.text
    assert f"/task/{klucz_z_innego_rocznika}?" not in tylko_100.text


@pytest.fixture
def zasob(con, task, tmp_path, monkeypatch) -> dict:
    """Zasób z ramką „cała strona" plus zeszyt zadań na dysku, z czego go wyciąć."""
    pdfium = pytest.importorskip("pypdfium2")
    monkeypatch.setenv("MIRROR_ROOT", str(tmp_path))
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blob"))
    (tmp_path / "raw").mkdir()
    document = pdfium.PdfDocument.new()
    document.new_page(595.0, 842.0)
    document.save(str(tmp_path / "raw" / "zeszyt.pdf"))
    document.close()

    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO document (segment, year, code, variants, session, kind, "
            "kind_source, url, path, pages) VALUES ('e8', 2025, 'OMAP', '100,X', "
            "'2025-05-01', 'paper', 'suffix', 'test://zeszyt', 'raw/zeszyt.pdf', 1) "
            "RETURNING id"
        )
        paper = cur.fetchone()["id"]
        cur.execute("SELECT exam_form_id FROM task_version WHERE id = %s",
                    (task["version"],))
        form_id = cur.fetchone()["exam_form_id"]
        cur.execute("INSERT INTO exam_form_document VALUES (%s, %s, 'paper')",
                    (form_id, paper))
        cur.execute(
            "INSERT INTO asset (task_version_id, kind, path, page, bbox) "
            "VALUES (%s, 'diagram', 'TEST/z20-0.png', 1, '{0,0,595,842}') RETURNING id",
            (task["version"],),
        )
        return {"id": cur.fetchone()["id"], "blob": tmp_path / "blob"}


def _ramka(zasob, x0="100", top="50", x1="300", bottom="150") -> dict:
    return {f"asset.{zasob['id']}.x0": x0, f"asset.{zasob['id']}.top": top,
            f"asset.{zasob['id']}.x1": x1, f"asset.{zasob['id']}.bottom": bottom,
            f"asset.{zasob['id']}.page": "1"}


def test_reczna_ramka_tnie_wycinek_i_liczy_sie_jako_poprawka(client, con, task, zasob):
    """Zawór nr 3: ramka dociągnięta ręcznie zamyka temat wycinka (G2.4.2).

    Zmiana ramki jest zmianą rekordu, więc zadanie ma wyjść jako `corrected` —
    inaczej S6 policzyłby ręczną robotę jako trafienie parsera.
    """
    response = _post(client, task, action="approve", **_full(task), **_ramka(zasob))

    assert response.status_code == 303
    assert (zasob["blob"] / "TEST" / "z20-0.png").exists()
    assert _state(con, task["id"])["review_status"] == "corrected"
    bbox = con.execute("SELECT bbox FROM asset WHERE id = %s",
                       (zasob["id"],)).fetchone()["bbox"]
    assert [float(v) for v in bbox] == [100.0, 50.0, 300.0, 150.0]


def test_ramka_poza_strona_nie_zapisuje_niczego(client, con, task, zasob):
    response = _post(client, task, action="approve", **_full(task),
                     **_ramka(zasob, x1="900"))

    assert response.status_code == 422
    assert "poza stronę" in response.text
    assert not (zasob["blob"] / "TEST" / "z20-0.png").exists()
    assert _state(con, task["id"])["review_status"] == "pending"


def test_przycisk_wytnij_nie_rozstrzyga_zadania(client, con, task, zasob):
    """„Wytnij" to podgląd ramki, nie zatwierdzenie — dziennik ma zostać pusty."""
    response = _post(client, task, action="crop", **_full(task), **_ramka(zasob))

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/task/{task['id']}?")
    assert (zasob["blob"] / "TEST" / "z20-0.png").exists()
    assert _state(con, task["id"])["review_status"] == "pending"
    assert _events(con) == []


def test_runda_wytnij_pamieta_usuniecie(client, con, task, zasob):
    """Skasowany wiersz w rundzie „Wytnij" jest poprawką, nie trafieniem parsera.

    Znacznik `edited_before` niósł wcześniej tylko edycje. Usunięcie wypadało
    z pomiaru: zadanie zatwierdzone zaraz potem wchodziło do S6 jako rekord,
    który parser trafił sam.
    """
    formularz = _full(task)
    formularz[f"delete.answer.{task['answer']}"] = "1"
    formularz.pop(f"answer.{task['answer']}.answer")

    wytnij = _post(client, task, action="crop", **formularz)
    assert "edited_before=1" in wytnij.headers["location"]

    bez_odpowiedzi = _full(task)
    bez_odpowiedzi.pop(f"answer.{task['answer']}.answer")
    _post(client, task, action="approve", edited_before="1", **bez_odpowiedzi)

    assert _state(con, task["id"])["review_status"] == "corrected"


def test_wycinek_nie_powstaje_gdy_zapis_sie_wycofuje(client, con, task, zasob):
    """Dysk nie cofa się razem z transakcją, więc cięcie idzie PO walidacji tekstu.

    Inaczej w blobie zostaje plik z ramką, której w bazie nie ma: ekran pokazuje
    wtedy wycinek niezgodny z polami obok, a licznik liczy go jako gotowy.
    """
    response = _post(client, task, action="approve",
                     **_full(task, **{f"condition.{task['condition']}.description": ""}),
                     **_ramka(zasob))

    assert response.status_code == 422
    assert not (zasob["blob"] / "TEST" / "z20-0.png").exists()


def test_ramka_wraca_do_formularza_po_bledzie(client, task, zasob):
    """Po nieudanej walidacji człowiek dostaje z powrotem TO, CO WPISAŁ.

    Odczyt czterech liczb z siatki kosztuje minutę; kasowanie go za cudzą
    literówkę w innym polu formularza jest karą bez związku z przewinieniem.
    """
    response = _post(client, task, action="approve",
                     **_full(task, **{f"condition.{task['condition']}.description": ""}),
                     **_ramka(zasob))

    assert response.status_code == 422
    for pole, wartosc in (("x0", "100"), ("top", "50"), ("x1", "300"), ("bottom", "150")):
        assert f'name="asset.{zasob["id"]}.{pole}" value="{wartosc}"' in response.text


def test_podglad_wycinka_i_strony_zeszytu(client, task, zasob):
    """Trasy obrazków: bez wycinka 404 z podpowiedzią, po wycięciu — PNG."""
    przed = client.get(f"/asset/{zasob['id']}.png")
    assert przed.status_code == 404
    assert "ramkę" in przed.text

    _post(client, task, action="crop", **_full(task), **_ramka(zasob))

    po = client.get(f"/asset/{zasob['id']}.png")
    assert po.status_code == 200
    assert po.headers["content-type"] == "image/png"

    strona = client.get(f"/asset/{zasob['id']}/page.png")
    assert strona.status_code == 200
    assert strona.headers["content-type"] == "image/png"


def test_strona_zeszytu_bez_zeszytu_mowi_co_zrobic(client, con, task, zasob):
    """Zasób bez wczytanego zeszytu ma powiedzieć, którym poleceniem go dowieźć."""
    with con.cursor() as cur:
        cur.execute("DELETE FROM exam_form_document WHERE role = 'paper'")

    response = client.get(f"/asset/{zasob['id']}/page.png")

    assert response.status_code == 404
    assert "--with-papers" in response.text


def _zamkniete(con, task, kryteria_gdzie_indziej: bool) -> int:
    """Zadanie zamknięte bez kryteriów w tym samym kluczu co `task`."""
    with con.cursor() as cur:
        cur.execute("SELECT marking_scheme_id FROM task WHERE id = %s", (task["id"],))
        document = cur.fetchone()["marking_scheme_id"]
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, "
            "page) VALUES (%s, '1', 1, 1, 'closed', 2) RETURNING id",
            (document,),
        )
        closed = cur.fetchone()["id"]
        if kryteria_gdzie_indziej:
            cur.execute(
                "INSERT INTO task (marking_scheme_id, number, position, max_points, "
                "kind, page) VALUES (%s, '2', 2, 1, 'closed', 2) RETURNING id",
                (document,),
            )
            sasiad = cur.fetchone()["id"]
            cur.execute("INSERT INTO criterion (task_id, points, position) "
                        "VALUES (%s, 1, 1)", (sasiad,))
    return closed


def test_zamkniete_bez_kryteriow_to_norma_gdy_klucz_ich_nie_ma(client, con, task):
    """Rocznik 2019: klucz podaje dla zadań zamkniętych samą odpowiedź wzorcową.

    Korektor ma zobaczyć kształt dokumentu, a nie szukać po kluczu sekcji,
    której w nim nie ma — inaczej rocznik 2019 kosztuje 90 razy po minucie
    szukania czegoś, czego nie ma.
    """
    closed = _zamkniete(con, task, kryteria_gdzie_indziej=False)

    response = client.get(f"/task/{closed}")

    assert response.status_code == 200
    assert "norma dokumentu" in response.text
    assert "dziura" not in response.text


def test_zamkniete_bez_kryteriow_to_dziura_gdy_sasiad_je_ma(client, con, task):
    """Niezgodność wewnątrz klucza znaczy, że parser przegapił sekcję."""
    closed = _zamkniete(con, task, kryteria_gdzie_indziej=True)

    response = client.get(f"/task/{closed}")

    assert response.status_code == 200
    assert "dziura" in response.text
    assert "norma dokumentu" not in response.text
