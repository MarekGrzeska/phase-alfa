"""Sprawdzian MODELU na jednym prawdziwym kluczu — następca `probe_load.py`.

`test_schema.py` sprawdza, czy więzy odrzucają złe dane. Ten plik odpowiada na
inne pytanie: **czy model udźwignie prawdziwy dokument**. Robi to na jednym
kluczu, za to z pełnym kompletem — sześć pytań, dla których ten model w ogóle
powstał.

Wymaga mirrora, więc pomija się, gdy go nie ma. Ładuje do OSOBNEJ bazy
tymczasowej, żeby nie zadeptać korpusu deweloperskiego.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import pytest

from schema.migrate import polaczenie as adres

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("pdfplumber")

pytestmark = [pytest.mark.integracyjny, pytest.mark.mirror]

KLUCZ = "data/raw/e8/2025/matematyka/OMAP-100-2505-zasady.pdf"
BAZA_TESTOWA = "klucz_test_corpus"

# Liczby zmierzone w sondzie 24.08.2026 na tym samym pliku. Rozjazd znaczy
# regresję parsera albo ładowarki, a nie „inny wynik".
OCZEKIWANE = {
    "task": 21,
    "task_version": 42,
    "criterion": 51,
    "criterion_condition": 73,
    "condition_expression": 14,
    "example_solution": 20,
    "rule": 17,
}


def _mirror_root() -> str:
    korzen = os.environ.get("MIRROR_ROOT", ".")
    if not os.path.isabs(korzen):
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        korzen = os.path.normpath(os.path.join(repo, korzen))
    return korzen


def _migruj(url: str) -> None:
    import subprocess
    import sys
    from pathlib import Path
    runner = Path(__file__).resolve().parents[1] / "schema" / "migrate.py"
    wynik = subprocess.run(
        [sys.executable, str(runner)],
        env={**os.environ, "DATABASE_URL": url, "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert wynik.returncode == 0, f"migracje nie przeszły:\n{wynik.stdout}{wynik.stderr}"


@pytest.fixture(scope="module")
def baza_z_kluczem():
    """Świeża baza + jeden klucz załadowany przez prawdziwą ładowarkę."""
    sciezka = os.path.join(_mirror_root(), KLUCZ)
    if not os.path.exists(sciezka):
        pytest.skip(f"brak mirrora: {sciezka}")

    try:
        bazowy = adres()
    except SystemExit as e:
        pytest.skip(f"brak konfiguracji bazy: {e}")

    try:
        adm = psycopg.connect(bazowy, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.skip(f"baza nieosiągalna: {e}")

    czesci = urlsplit(bazowy)
    url = urlunsplit(czesci._replace(path=f"/{BAZA_TESTOWA}"))
    with adm:
        with adm.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{BAZA_TESTOWA}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{BAZA_TESTOWA}"')
        try:
            _migruj(url)
            from parsers.omap_e8 import loader
            from parsers.omap_e8 import parser as K

            k = K.czytaj_klucz(sciezka)
            meta = {
                "segment": "e8", "rocznik": "2025", "kod": "OMAP",
                "warianty": "100", "sesja_data": "2025-05-01",
                "typ": "zasady_oceniania", "zrodlo_typu": "prefiks",
                "url": "test://omap-2505", "sciezka": KLUCZ,
                "przedmiot": "matematyka",
            }
            with psycopg.connect(url, autocommit=True) as con:
                loader.Ladowarka(con).zaladuj(k, meta)
                yield con
        finally:
            with adm.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{BAZA_TESTOWA}" WITH (FORCE)')


def licznik(con, tabela: str, warunek: str = "") -> int:
    sql = f"SELECT count(*) FROM {tabela} {warunek}"  # noqa: S608 - nazwy ze stałych
    return con.execute(sql).fetchone()[0]


@pytest.mark.parametrize(("tabela", "ile"), sorted(OCZEKIWANE.items()))
def test_liczby_zgadzaja_sie_z_sonda(baza_z_kluczem, tabela, ile):
    assert licznik(baza_z_kluczem, tabela) == ile


def test_jeden_klucz_obsluguje_wiele_form(baza_z_kluczem):
    """Sedno modelu N:M. OMAP-100-2505 deklaruje sześć form arkusza —
    „trójka plików" z „Kopalni CKE" nie miałaby tu gdzie stanąć."""
    assert licznik(baza_z_kluczem, "exam_form") >= 6


def test_blizniaki_maja_rozne_odpowiedzi_przy_wspolnych_kryteriach(baza_z_kluczem):
    """Zadania 1–15 mają wersje X i Y z RÓŻNYMI odpowiedziami, a kryteria
    wspólne. To jest powód, dla którego `criterion` wisi na `task`,
    a `model_answer` na `task_version`."""
    (ile,) = baza_z_kluczem.execute("""
        SELECT count(*) FROM (
            SELECT tv.task_id
            FROM task_version tv
            JOIN model_answer m ON m.task_version_id = tv.id
            GROUP BY tv.task_id
            HAVING count(DISTINCT m.answer) > 1) s""").fetchone()
    assert ile > 0, "żadne zadanie nie ma różnych odpowiedzi w wersjach X i Y"


def test_mapa_brakow_liczy_sie_bez_zgadywania(baza_z_kluczem):
    """Widok `tasks_per_requirement` jest testem schematu: jeśli da się go
    wykonać i coś zwraca, model utrzymuje mapowanie na podstawę programową."""
    wiersze = baza_z_kluczem.execute(
        "SELECT path, tasks FROM tasks_per_requirement ORDER BY tasks DESC LIMIT 5"
    ).fetchall()
    assert wiersze, "mapa braków pusta — zerwane parowanie zadania z wymaganiem"
    assert all(t > 0 for _, t in wiersze)


def test_kryteria_zachowuja_strukture_progow_i_alternatyw(baza_z_kluczem):
    """Trzy poziomy dysjunkcji: próg → warunek → zapis równoważny.
    Spłaszczenie do jednego pola tekstowego znaczy, że silnik dostanie akapit
    prozy zamiast listy sprawdzalnych alternatyw."""
    (ile,) = baza_z_kluczem.execute("""
        SELECT count(*) FROM criterion c
        WHERE EXISTS (SELECT 1 FROM criterion_condition cc
                      WHERE cc.criterion_id = c.id)""").fetchone()
    assert ile >= 20, f"tylko {ile} kryteriów ma warunki"

    (z_zapisami,) = baza_z_kluczem.execute("""
        SELECT count(DISTINCT cc.criterion_id)
        FROM criterion_condition cc
        JOIN condition_expression ce ON ce.condition_id = cc.id""").fetchone()
    assert z_zapisami > 0, "zapisy równoważne przepadły"


def test_reguly_przekrojowe_maja_zakres_zadan(baza_z_kluczem):
    """„Uwagi ogólne" to reguły arkusza, nie kryteria zadania — działają
    w kroku Compose, po ocenie wszystkich kryteriów naraz. Część obowiązuje
    tylko na wycinku arkusza, stąd `tasks_from`/`tasks_to`."""
    (z_zakresem,) = baza_z_kluczem.execute(
        "SELECT count(*) FROM rule WHERE tasks_from IS NOT NULL").fetchone()
    assert z_zakresem > 0, "żadna reguła nie ma zakresu zadań"
