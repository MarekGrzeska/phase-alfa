"""Liczby S8 i ochrona ścieżek — części, które nie potrzebują bazy.

Prognoza z tych funkcji rozstrzyga zawór z G2.2.2 („tempo × 7 roczników mieści
się w planie?"), więc ma być sprawdzona osobno od SQL-a, który dowozi wiersze.
"""

from __future__ import annotations

import pytest

from correction import db, pages, stats


@pytest.mark.parametrize(("number", "widoczna"), [
    ("16", True), ("18", True), ("21", True), ("15", False), ("22", False),
    ("18.2", True),
])
def test_regula_obejmuje_cale_zakresy_a_nie_same_konce(number, widoczna):
    """„W zadaniach 16–21 sam poprawny wynik to 0 punktów" dotyczy też zadania 18.

    Dopasowanie po krańcach zakresu pokazywało tę regułę wyłącznie przy 16 i 21,
    czyli znikała z ekranu przy większości zadań, których dotyczy — a korekta
    kryteriów bez reguły arkusza ocenia co innego, niż ocenia klucz.
    """
    regula = {"tasks_from": "16", "tasks_to": "21"}
    assert db.rule_applies(regula, number) is widoczna


def test_regula_bez_zakresu_dotyczy_calego_arkusza():
    assert db.rule_applies({"tasks_from": None, "tasks_to": None}, "1") is True


def test_regula_przypieta_do_jednego_zadania():
    """Uwaga spod zadania wchodzi z zakresem N–N, nie z pustym."""
    regula = {"tasks_from": "16", "tasks_to": "16"}
    assert db.rule_applies(regula, "16") is True
    assert db.rule_applies(regula, "17") is False


def test_stan_bez_zadnego_rozstrzygniecia_nie_dzieli_przez_zero():
    summary = stats.status_summary(
        {"pending": 10, "approved": 0, "corrected": 0, "rejected": 0})
    assert summary["done_share"] == 0.0
    assert summary["hit_share"] == 0.0
    assert summary["pending"] == 10


def test_trafienia_parsera_liczy_sie_po_korpusie_nie_po_decyzjach():
    """Odrzucone nie są ani trafieniem, ani poprawką — są dziurą w korpusie.

    Gdyby wchodziły do mianownika, S6/S8 spadałoby za każdym razem, gdy klucz
    okaże się nie do uratowania — czyli pomiar jakości parsera zależałby
    od jakości dokumentu CKE.
    """
    summary = stats.status_summary(
        {"pending": 0, "approved": 6, "corrected": 2, "rejected": 2})
    assert summary["hit_share"] == pytest.approx(6 / 8)
    assert summary["decided"] == 10
    assert summary["done_share"] == 1.0


def test_pusty_dziennik_daje_zera_a_nie_wyjatek():
    assert stats.duration_summary([]) == {"events": 0, "median": 0.0,
                                          "total": 0.0, "long": 0}


def test_mediana_nie_daje_sie_przewrocic_porzuconemu_formularzowi():
    """Formularz zostawiony na noc wchodzi do dziennika jako praca.

    Średnia z tych czasów (7382 s) kazałaby prognozować dwa dni na zadanie.
    Mediana widzi to, co widać: sześćdziesiąt sekund.
    """
    seconds = [40.0, 55.0, 60.0, 65.0, 80.0, 36_000.0]
    durations = stats.duration_summary(seconds)

    assert durations["median"] == pytest.approx(62.5)
    assert durations["long"] == 1, "długa sesja ma być policzona, nie ukryta"
    assert durations["total"] == pytest.approx(sum(seconds))

    ahead = stats.forecast(pending=100, median_seconds=durations["median"])
    assert ahead["hours"] == pytest.approx(100 * 62.5 / 3600)


def test_raport_tekstowy_niesie_liczby_do_wniosku():
    numbers = {
        "status": stats.status_summary(
            {"pending": 4, "approved": 3, "corrected": 2, "rejected": 1}),
        "durations": stats.duration_summary([60.0, 120.0]),
        "forecast": stats.forecast(4, 90.0),
        "years": [{"year": 2025, "total": 10, "pending": 4, "approved": 3,
                   "corrected": 2, "rejected": 1}],
        "assets": {"total": 14, "framed": 9, "cropped": 9},
    }
    text = stats.as_text(numbers)

    assert "S8 — trafienia parsera : 60.0%" in text
    assert "2025" in text
    assert "PROGNOZA" in text
    # Krok 3 pilotu domyka się, gdy zadania z rysunkiem MAJĄ wycinek — raport
    # ma to mówić liczbą, bo inaczej „zrobione" opiera się na pamięci.
    assert "z plikiem PNG w blobie : 9" in text


def test_sciezka_z_bazy_nie_wychodzi_poza_mirror():
    """Nazwy plików biorą się z korpusu CKE, więc `..` w ścieżce nie jest bajką.

    Ten sam sprawdzian, który `DiskBlobStore` robi po stronie C#.
    """
    with pytest.raises(pages.PageUnavailable, match="poza mirror"):
        pages.source_pdf("../../../etc/passwd")


def test_sciezka_wewnatrz_mirrora_przechodzi():
    """Bramka ma przepuszczać normalne ścieżki — inaczej niczego nie sprawdza."""
    assert pages.source_pdf("data/raw/e8/2025/x.pdf").name == "x.pdf"
