"""Rodowód opisu rysunku — maszyna stanów, na której stoi pomiar S7 (G2.5.2)."""

from __future__ import annotations

import pytest

from correction import assets, stats


class FakeCursor:
    def __init__(self) -> None:
        self.updates: list[tuple] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple) -> None:
        self.updates.append(params)
        self.rowcount = 1


def make_asset(status: str, description: str | None = None) -> dict:
    return {"id": 7, "path": "OMAP/2505/100/0/z16-0.png",
            "description": description, "description_status": status}


def submit(asset: dict, text: str, approve: bool = False):
    """Jeden zapis opisu. Oddaje nowy status albo `None`, gdy nic nie tknął."""
    form = {"asset.7.description": text}
    if approve:
        form["asset.7.approve_description"] = "1"
    cursor, described, problems = FakeCursor(), {}, []
    assets.save_description(cursor, asset, form, described, problems)
    assert not problems, problems
    return (cursor.updates[0][1] if cursor.updates else None), described


def test_model_text_taken_as_is_counts_as_a_hit():
    status, _ = submit(make_asset("auto", "Wykres słupkowy…"), "Wykres słupkowy…",
                       approve=True)
    assert status == "approved"


def test_second_approval_of_unchanged_text_writes_nothing():
    status, described = submit(make_asset("approved", "Wykres…"), "Wykres…",
                               approve=True)
    assert status is None and described == {}


def test_editing_model_text_settles_s7_without_waiting_for_approval():
    """Edycja bez zaznaczenia „zatwierdź" zostawiała stan `auto`, więc tekst
    CZŁOWIEKA wchodził potem do licznika trafień modelu."""
    status, _ = submit(make_asset("auto", "Wykres słupkowy…"),
                       "Wykres słupkowy, oś Y w kg.")
    assert status == "corrected"


def test_corrected_text_never_gets_promoted_to_a_hit():
    status, described = submit(make_asset("corrected", "Mój opis."), "Mój opis.",
                               approve=True)
    assert status is None and described == {}


def test_overwriting_an_approved_text_is_a_correction():
    status, _ = submit(make_asset("approved", "Wykres…"), "Wykres słupkowy, oś Y w kg.")
    assert status == "corrected"


def test_text_written_from_scratch_stays_outside_the_measurement():
    """Modelu tu nie było, więc nie ma czego trafić ani zepsuć. Jako `corrected`
    taki opis obniżał S7 za pracę, o którą pomiar nie pyta."""
    status, _ = submit(make_asset("none"), "Oś liczbowa od -3 do 3.", approve=True)
    assert status == "manual"


def test_own_text_stays_own_after_further_edits():
    status, _ = submit(make_asset("manual", "Oś liczbowa."), "Oś liczbowa od -3 do 3.")
    assert status == "manual"


def test_cleared_text_goes_back_to_the_start():
    """Pusty rekord w mianowniku S7 byłby rozstrzygnięciem, którego nie ma."""
    status, _ = submit(make_asset("corrected", "Mój opis."), "   ")
    assert status == "none"


def test_empty_text_cannot_be_approved():
    cursor, described, problems = FakeCursor(), {}, []
    assets.save_description(cursor, make_asset("auto", "Wykres…"),
                            {"asset.7.description": "  ",
                             "asset.7.approve_description": "1"},
                            described, problems)
    assert problems and not cursor.updates


def test_asset_missing_from_the_form_is_left_alone():
    cursor, described, problems = FakeCursor(), {}, []
    assets.save_description(cursor, make_asset("auto", "Wykres…"), {},
                            described, problems)
    assert not cursor.updates and not problems


def test_descriptions_are_counted_apart_from_parser_corrections():
    """`db.decide` czyta `edited`; opis w tym samym słowniku zamieniał każde
    zatwierdzenie alt-textu w „parser się pomylił" i obniżał S8."""
    _, described = submit(make_asset("auto", "Wykres…"), "Wykres…", approve=True)
    assert described == {"approved": 1}


@pytest.mark.parametrize("status", assets.DESCRIPTION_STATUSES)
def test_every_status_has_a_transition_for_human_edits(status):
    """Brak wpisu to `KeyError` w trakcie zapisu korekty — po dodaniu stanu
    migracją ma upaść tutaj, a nie u człowieka przy formularzu."""
    assert assets._AFTER_HUMAN_EDIT[status] in assets.DESCRIPTION_STATUSES


def test_s7_keeps_own_descriptions_out_of_the_denominator():
    measure = stats.s7({"total": 10, "description_none": 1, "description_auto": 2,
                        "description_approved": 3, "description_corrected": 1,
                        "description_manual": 3})
    assert measure["hit_share"] == pytest.approx(3 / 4)
    assert measure["manual"] == 3
