"""Ochrona przed przeładowaniem klucza po korekcie.

`loader._wyczysc_klucz` z założenia kasuje to, co klucz zapisał poprzednim
razem — i to jest poprawne, dopóki nikt tych rekordów nie tknął. Po pierwszej
ręcznej poprawce ta sama linijka kasuje pracę człowieka, czyli najdroższy zasób
całego A2. Ten test istnieje po to, żeby odmowa była WIDZIANA, a nie założona.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from parsers.omap_e8 import loader

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.integracyjny

URL = "test://rerun-guard"

META = {
    "segment": "e8", "rocznik": "2025", "kod": "OMAP", "warianty": "100",
    "sesja_data": "2025-05-01", "typ": "zasady_oceniania", "zrodlo_typu": "sufiks",
    "url": URL, "sciezka": "OMAP-100-2505-zasady.pdf", "przedmiot": "matematyka",
}

# Klucz bez zadań: bramka stoi PRZED czymkolwiek innym w `_zaladuj`, więc
# do jej sprawdzenia nie trzeba parsować PDF-a. Pola są dokładnie te, których
# dotyka ładowarka — brak któregokolwiek byłby błędem testu, nie kodu.
PUSTY_KLUCZ = SimpleNamespace(termin="2025-05-01", rezimy=[], egzamin="e8",
                              formy=[], zadania=[], reguly=[], stron=1,
                              dialekt="e8-2020")


@pytest.fixture
def baza(fresh_database):
    with psycopg.connect(fresh_database, autocommit=True) as con:
        yield con


@pytest.fixture
def klucz_po_korekcie(baza) -> int:
    """Dokument z jednym zadaniem oznaczonym jako poprawione."""
    with baza.cursor() as cur:
        cur.execute("TRUNCATE document, task, exam_form, requirement_regime "
                    "RESTART IDENTITY CASCADE")
        cur.execute(
            "INSERT INTO document (segment, year, code, kind, kind_source, url, path) "
            "VALUES ('e8', 2025, 'OMAP', 'marking_scheme', 'suffix', %s, %s) RETURNING id",
            (URL, META["sciezka"]),
        )
        (doc_id,) = cur.fetchone()
        cur.execute(
            "INSERT INTO task (marking_scheme_id, number, position, max_points, kind, "
            "review_status) VALUES (%s, '1', 1, 2, 'open_short', 'corrected')",
            (doc_id,),
        )
    return doc_id


def _zadania(con, doc_id: int) -> int:
    return con.execute("SELECT count(*) FROM task WHERE marking_scheme_id = %s",
                       (doc_id,)).fetchone()[0]


def test_ladowarka_odmawia_skasowania_korekty(baza, klucz_po_korekcie):
    with pytest.raises(loader.ReviewedKeyError) as wyjatek:
        loader.Ladowarka(baza).zaladuj(PUSTY_KLUCZ, META)

    assert wyjatek.value.reviewed == 1
    assert "--overwrite-reviewed" in str(wyjatek.value)
    assert _zadania(baza, klucz_po_korekcie) == 1, "zadanie zniknęło mimo odmowy"


def test_zgoda_jest_jawna_i_dziala(baza, klucz_po_korekcie):
    """Z jawną zgodą klucz przeładowuje się normalnie — bramka nie jest ślepym zaułkiem."""
    loader.Ladowarka(baza, overwrite_reviewed=True).zaladuj(PUSTY_KLUCZ, META)
    assert _zadania(baza, klucz_po_korekcie) == 0


def test_klucz_bez_korekty_przechodzi(baza, klucz_po_korekcie):
    """Bramka pyta o KOREKTĘ, nie o istnienie zadań — inaczej blokowałaby każdy rerun."""
    with baza.cursor() as cur:
        cur.execute("UPDATE task SET review_status = 'pending' "
                    "WHERE marking_scheme_id = %s", (klucz_po_korekcie,))

    loader.Ladowarka(baza).zaladuj(PUSTY_KLUCZ, META)
    assert _zadania(baza, klucz_po_korekcie) == 0


def test_runner_widzi_klucze_po_korekcie(baza, klucz_po_korekcie):
    """Zapytanie wstępne runnera — pomija klucz PRZED parsowaniem, nie po."""
    from parsers.omap_e8.run import reviewed_by_url

    assert reviewed_by_url(baza).get(URL) == 1


def test_wyczysc_broni_takze_dziennika_korekty(baza, klucz_po_korekcie):
    """Dziennik S8 ginie w kaskadzie TRUNCATE-a mimo `ON DELETE SET NULL`.

    Scenariusz nie jest teoretyczny: po przeładowaniu kluczy z
    `--overwrite-reviewed` żadne zadanie nie jest już „po korekcie", więc
    pierwsza bramka przepuszcza — a w dzienniku leżą wtedy wszystkie zmierzone
    czasy z dotychczasowej pracy.
    """
    from parsers.omap_e8.run import wipe_refusal

    with baza.cursor() as cur:
        cur.execute("UPDATE task SET review_status = 'pending'")
        cur.execute("INSERT INTO correction_event (task_id, action, started_at) "
                    "VALUES (NULL, 'approve', now())")

    powod = wipe_refusal(baza)
    assert powod is not None
    assert "dziennik" in powod

    with baza.cursor() as cur:
        cur.execute("TRUNCATE correction_event")
    assert wipe_refusal(baza) is None
