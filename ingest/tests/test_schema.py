"""Sprawdzian schematu: czy migracje dają bazę, na którą liczy reszta planu.

Test celowo NIE jest listą tabel przepisaną z migracji — taki test przechodzi
zawsze i nie mówi nic. Sprawdza dwie rzeczy, które da się zepsuć po cichu:
więzy naprawdę odrzucają złe dane, a widoki dają się wykonać.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.integracyjny

TABELE = {
    "rezim", "wymaganie", "dokument", "forma", "forma_dokument",
    "zadanie", "zadanie_wymaganie", "zadanie_wersja", "odpowiedz_wzorcowa",
    "kryterium", "kryterium_warunek", "warunek_zapis",
    "rozwiazanie_przykladowe", "przyklad_odpowiedzi", "regula", "zasob",
    "schema_migrations",
}

WIDOKI = {"zadania_per_wymaganie", "blizniaki"}


@pytest.fixture(scope="module")
def conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("brak DATABASE_URL — `task up` stawia bazę")
    try:
        with psycopg.connect(url, connect_timeout=5) as c:
            yield c
    except psycopg.OperationalError as e:
        pytest.skip(f"baza nieosiągalna: {e}")


def test_komplet_tabel(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        )
        sa = {r[0] for r in cur.fetchall()}
    brakuje = TABELE - sa
    assert not brakuje, f"brakuje tabel: {sorted(brakuje)}"


def test_komplet_widokow(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.views WHERE table_schema = 'public'"
        )
        sa = {r[0] for r in cur.fetchall()}
    assert sa >= WIDOKI, f"brakuje widoków: {sorted(WIDOKI - sa)}"


def test_widoki_daja_sie_wykonac(conn):
    """Widok, który się nie kompiluje, jest błędem schematu, nie stylu."""
    with conn.cursor() as cur:
        for widok in WIDOKI:
            cur.execute(f"SELECT * FROM {widok} LIMIT 0")  # noqa: S608 - nazwa ze stałej
    conn.rollback()


def test_kolacja_pl_icu_istnieje(conn):
    """Polskie sortowanie ma być dostępne mimo clustra w C.UTF-8."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_collation WHERE collname = 'pl_icu'")
        assert cur.fetchone(), "brak kolacji pl_icu — patrz migracja 0001"


def test_kolacja_pl_icu_sortuje_po_polsku(conn):
    """ł ma stać między l a m, a nie na końcu alfabetu jak w C.UTF-8."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT x FROM (VALUES ('mama'), ('łąka'), ('lampa')) AS t(x) "
            "ORDER BY x COLLATE pl_icu"
        )
        assert [r[0] for r in cur.fetchall()] == ["lampa", "łąka", "mama"]
    conn.rollback()


def test_wiez_kryterium_odrzuca_dwa_progi_o_tej_samej_punktacji(conn):
    """To jest TEN więz, który złapał prawdziwy błąd w sondzie.

    Sekcja reguł przekrojowych stoi między zadaniami, więc podział tekstu po
    nagłówkach doklejał ją do zadania poprzedzającego, a jej zdanie
    „…to otrzymuje 0 punktów" udawało drugi próg 0 pkt. Test pilnuje, żeby
    ktoś tego więzu nie poluzował „bo parser się wywalał".
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rezim (kod, nazwa, sesja_od) "
            "VALUES ('test-wiez', 'test', '2024-01-01') RETURNING id"
        )
        cur.execute(
            "INSERT INTO dokument (segment, rocznik, kod, typ, zrodlo_typu, url, sciezka) "
            "VALUES ('e8', 2025, 'OMAP', 'zasady_oceniania', 'sufiks', "
            "'test://wiez', 'test') RETURNING id"
        )
        (dok_id,) = cur.fetchone()
        cur.execute(
            "INSERT INTO zadanie (klucz_id, numer, kolejnosc, punkty_max, typ) "
            "VALUES (%s, '20', 20, 3, 'otwarte_krotkie') RETURNING id",
            (dok_id,),
        )
        (zad_id,) = cur.fetchone()

        cur.execute(
            "INSERT INTO kryterium (zadanie_id, punkty, kolejnosc) VALUES (%s, 0, 1)",
            (zad_id,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO kryterium (zadanie_id, punkty, kolejnosc) VALUES (%s, 0, 2)",
                (zad_id,),
            )
    conn.rollback()


def test_wiez_punkty_max_odrzuca_bzdure(conn):
    """CHECK (punkty_max BETWEEN 0 AND 60) — literówka w puli nie wchodzi cicho."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO dokument (segment, rocznik, kod, typ, zrodlo_typu, url, sciezka) "
            "VALUES ('e8', 2025, 'OMAP', 'zasady_oceniania', 'sufiks', "
            "'test://punkty', 'test') RETURNING id"
        )
        (dok_id,) = cur.fetchone()
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO zadanie (klucz_id, numer, kolejnosc, punkty_max, typ) "
                "VALUES (%s, '1', 1, 999, 'zamkniete')",
                (dok_id,),
            )
    conn.rollback()


def test_migracje_zapisane(conn):
    """Baza wie, którą wersją schematu jest — inaczej nie da się jej odtworzyć."""
    with conn.cursor() as cur:
        cur.execute("SELECT wersja FROM schema_migrations ORDER BY wersja")
        wersje = [r[0] for r in cur.fetchall()]
    assert wersje, "schema_migrations puste — migracje nie przeszły"
    assert wersje == sorted(wersje)
