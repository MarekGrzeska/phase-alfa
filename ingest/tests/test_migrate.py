"""Sprawdzian runnera migracji — na osobnej, tymczasowej bazie.

Testuje to, czego `test_schema.py` sprawdzić nie może, bo tamten patrzy na
gotowy wynik: czy runner zachowuje się poprawnie, gdy coś pójdzie nie tak.

Najważniejszy z tych testów to `test_migracja_ktora_padla_nie_cofa_poprzedniej`.
Pilnuje obietnicy „jeden plik = jedna transakcja", która przez pierwsze dwa
tygodnie NIE była prawdziwa: połączenie bez `autocommit` powodowało, że
`conn.transaction()` zakładał punkt przywracania wewnątrz już otwartej
transakcji, więc wszystkie migracje commitowały się razem na końcu.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

from schema.migrate import polaczenie as adres

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.integracyjny

RUNNER = Path(__file__).resolve().parents[1] / "schema" / "migrate.py"
BAZA_TESTOWA = "klucz_test_migrate"


def _url_bazy(url: str, nazwa: str) -> str:
    czesci = urlsplit(url)
    return urlunsplit(czesci._replace(path=f"/{nazwa}"))


@pytest.fixture
def baza():
    """Tworzy pustą bazę na czas testu i kasuje ją po nim.

    Osobna baza, bo runner wykonuje DDL i zapisuje do `schema_migrations` —
    puszczony na bazie deweloperskiej zadeptałby korpus.
    """
    try:
        url = adres()
    except SystemExit as e:
        pytest.skip(f"brak konfiguracji bazy: {e}")

    # CREATE DATABASE nie działa w transakcji, stąd autocommit
    try:
        adm = psycopg.connect(url, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.skip(f"baza nieosiągalna: {e}")

    with adm:
        with adm.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{BAZA_TESTOWA}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{BAZA_TESTOWA}"')
        try:
            yield _url_bazy(url, BAZA_TESTOWA)
        finally:
            with adm.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{BAZA_TESTOWA}" WITH (FORCE)')


def uruchom(url: str, katalog: Path, *dodatkowe: str) -> subprocess.CompletedProcess:
    """Uruchamia runner na wskazanej bazie i zwraca wynik.

    PYTHONIOENCODING jest tu KONIECZNE, nie kosmetyczne. Na Windows proces
    potomny pisze na przechwycone wyjście w kodowaniu konsoli (cp1250), więc
    polskie znaki i myślniki z komunikatów runnera rozsypywały dekodowanie
    po stronie testu — a `stdout` wychodził wtedy jako None i test wywalał się
    na TypeError zamiast pokazać, co poszło nie tak.
    """
    return subprocess.run(
        [sys.executable, str(RUNNER), "--migrations", str(katalog), *dodatkowe],
        env={**os.environ, "DATABASE_URL": url, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def zapisz(katalog: Path, nazwa: str, sql: str) -> None:
    (katalog / nazwa).write_text(sql, encoding="utf-8", newline="\n")


def test_migracja_ktora_padla_nie_cofa_poprzedniej(baza, tmp_path):
    """Sedno: pierwsza migracja ma ZOSTAĆ w bazie, gdy druga się wywali.

    Gdyby wszystkie migracje leciały w jednej wspólnej transakcji, błąd drugiej
    cofnąłby też pierwszą — a na ekranie i tak stałoby, że pierwsza weszła.
    """
    zapisz(tmp_path, "0001_dobra.sql", "CREATE TABLE pierwsza (id integer);")
    zapisz(tmp_path, "0002_zla.sql", "TO NIE JEST POPRAWNY SQL;")

    wynik = uruchom(baza, tmp_path)
    assert wynik.returncode != 0, "runner powinien zgłosić błąd drugiej migracji"

    with psycopg.connect(baza) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.pierwsza') IS NOT NULL")
        (jest,) = cur.fetchone()
        assert jest, "pierwsza migracja zniknęła — to NIE są osobne transakcje"

        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        assert [r[0] for r in cur.fetchall()] == ["0001_dobra"]


def test_druga_proba_nic_nie_robi(baza, tmp_path):
    """Idempotencja: uruchomienie na aktualnej bazie ma być bezczynne."""
    zapisz(tmp_path, "0001_tabela.sql", "CREATE TABLE cos (id integer);")

    assert uruchom(baza, tmp_path).returncode == 0
    drugi = uruchom(baza, tmp_path)
    assert drugi.returncode == 0
    assert "nic do zrobienia" in drugi.stdout


def test_podmiana_zastosowanej_migracji_przerywa(baza, tmp_path):
    """Zastosowanej migracji się nie edytuje — inaczej dwie maszyny z tą samą
    wersją schematu miałyby różne bazy."""
    zapisz(tmp_path, "0001_tabela.sql", "CREATE TABLE cos (id integer);")
    assert uruchom(baza, tmp_path).returncode == 0

    zapisz(tmp_path, "0001_tabela.sql", "CREATE TABLE cos (id integer);\n-- dopisek\n")
    wynik = uruchom(baza, tmp_path)
    assert wynik.returncode != 0
    assert "ROZJAZD" in wynik.stdout + wynik.stderr


def test_bom_i_crlf_nie_licza_sie_jako_podmiana(baza, tmp_path):
    """Suma ma reagować na zmianę TREŚCI, nie na to, czym plik zapisano.

    PowerShell na Windows dopisuje BOM przy `Set-Content -Encoding utf8`,
    a git potrafi wydać plik z CRLF — żadne z tych dwóch nie jest podmianą.
    """
    tresc = "CREATE TABLE cos (id integer);\n"
    zapisz(tmp_path, "0001_tabela.sql", tresc)
    assert uruchom(baza, tmp_path).returncode == 0

    # ten sam SQL, ale z BOM-em i zakończeniami linii w stylu Windows
    (tmp_path / "0001_tabela.sql").write_bytes(
        b"\xef\xbb\xbf" + tresc.replace("\n", "\r\n").encode("utf-8")
    )
    wynik = uruchom(baza, tmp_path)
    assert wynik.returncode == 0, f"BOM albo CRLF uznane za podmianę:\n{wynik.stdout}"


def test_status_niczego_nie_zmienia(baza, tmp_path):
    zapisz(tmp_path, "0001_tabela.sql", "CREATE TABLE cos (id integer);")

    wynik = uruchom(baza, tmp_path, "--status")
    assert wynik.returncode == 0
    assert "[ ] 0001_tabela" in wynik.stdout

    with psycopg.connect(baza) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.cos') IS NULL")
        (nie_ma,) = cur.fetchone()
        assert nie_ma, "--status utworzył tabelę, choć miał tylko pokazać stan"
