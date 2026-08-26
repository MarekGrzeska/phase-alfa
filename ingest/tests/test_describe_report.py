"""Raport opisów rysunków — mianownik pokrycia (G2.5.2).

Stany wypisane w raporcie z pamięci gubiły ten dodany migracją: suma była
mniejsza od korpusu, a pokrycie liczyło się po mianowniku, który kurczył się
z każdą poprawką człowieka.
"""

from __future__ import annotations

from correction import assets, describe, llm


def test_report_counts_every_description_status():
    totals = {"none": 100, "auto": 200, "approved": 200,
              "corrected": 100, "manual": 7}

    text = describe.report(llm.Spend(), totals)

    assert "zasobów razem          : 607" in text
    assert "poprawione (corrected) : 100" in text
    assert "własne człowieka       : 7" in text


def test_coverage_is_measured_against_the_whole_corpus():
    totals = {"none": 100, "auto": 200, "approved": 200,
              "corrected": 100, "manual": 0}

    assert "pokrycie opisami       : 83.3%" in describe.report(llm.Spend(), totals)


def test_report_knows_every_status_in_the_schema():
    """Wartownik: stan dodany migracją, a nieznany raportowi, ma go wywalić
    na `KeyError`, a nie po cichu zaniżyć sumę."""
    totals = dict.fromkeys(assets.DESCRIPTION_STATUSES, 1)

    assert "zasobów razem          : 5" in describe.report(llm.Spend(), totals)


def test_empty_corpus_does_not_divide_by_zero():
    totals = dict.fromkeys(assets.DESCRIPTION_STATUSES, 0)

    assert "pokrycie" not in describe.report(llm.Spend(), totals)


def test_force_cannot_reach_human_work():
    """Stany ludzkie odsiewa samo zapytanie, niezależnie od `--force`."""
    assert "NOT (a.description_status = ANY(%(human)s))" in describe.SQL_ASSETS
    assert set(describe.HUMAN_STATUSES) == {"approved", "corrected", "manual"}
