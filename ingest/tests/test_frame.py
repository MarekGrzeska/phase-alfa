"""Ramka z siatki (`correction.frame`, plan A2-auto X3) — przeliczenie i sito ramek.

Wywołań LLM nie ma w CI: sprawdza się, że piksele obrazu przechodzą na punkty
PDF przez skalę renderu, które ramki wolno zapisać, i że schemat jest domknięty.
"""

from __future__ import annotations

from correction import frame
from correction.prefill import strict_schema

A4_AT_2X = (1190, 1684)          # 595 × 842 pt w skali 2


def _frame(**overrides) -> frame.Frame:
    values = {"found": True, "x0": 200.0, "top": 400.0, "x1": 600.0, "bottom": 700.0,
              "reason": "wykres słupkowy z osiami"}
    values.update(overrides)
    return frame.Frame(**values)


def test_schema_is_strict():
    schema = strict_schema(frame.Frame)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"found", "x0", "top", "x1", "bottom", "reason"}


def test_pixels_become_points_through_the_render_scale():
    box, why = frame.to_points(_frame(), A4_AT_2X, scale=2.0)
    assert why is None
    assert box == [100.0, 200.0, 300.0, 350.0]


def test_not_found_is_refused_with_the_models_reason():
    box, why = frame.to_points(_frame(found=False, reason="zadanie bez rysunku"), A4_AT_2X)
    assert box is None and why == "zadanie bez rysunku"


def test_whole_page_box_is_refused():
    """Zero w lewym górnym rogu to ramka parsera „cała strona" — model nie ma
    prawa jej odtworzyć, bo raport liczyłby ją jako dociągniętą."""
    _, why = frame.to_points(_frame(x0=0.0, top=0.0), A4_AT_2X)
    assert "cała strona" in why


def test_box_far_outside_the_page_is_refused_not_clamped():
    """Współrzędne dwa razy za duże to inna skala, nie rysunek przy krawędzi."""
    _, why = frame.to_points(_frame(x1=2100.0, bottom=2600.0), A4_AT_2X)
    assert "poza stroną" in why


def test_small_overshoot_is_clamped_to_the_page():
    box, why = frame.to_points(_frame(x0=-4.0, x1=1196.0), A4_AT_2X)
    assert why is None
    assert box[0] == 0.0 and box[2] == 595.0


def test_too_small_box_is_refused():
    _, why = frame.to_points(_frame(x1=220.0), A4_AT_2X)
    assert "za mała" in why
