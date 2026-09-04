"""Golden set (`golden.*`, plan A2-auto X5) — kształt pliku i podział ról.

Wywołań LLM nie ma w CI: sprawdza się, że autor nie dostaje klucza, gdy ma
treść zadania (inaczej odpowiedzi cytują rozwiązanie przykładowe), że przy
braku treści rekonstruuje ją z klucza i że plik niesie provenance.
"""

from __future__ import annotations

from correction.prefill import strict_schema
from golden import common, generate, grade


def _task(content: str | None) -> dict:
    return {"id": 1, "number": "18", "max_points": 3, "kind": "open_extended",
            "year": 2025, "session": "2025-05-14", "code": "OMAP", "exam_form": "OMAP-100-X",
            "content": content,
            "solutions": [{"method": "I", "points": 3, "content": "P = 12 · 8 = 96"}],
            "descriptions": ["prostokąt 12 na 8"], "rules": [], "marking_text": "3 pkt …"}


def test_placeholder_is_not_real_content():
    assert common.has_real_content("Prostokąt o bokach 12 i 8 …")
    assert not common.has_real_content(
        "ZADANIE 18. ZNAJDUJE SIĘ NA KARCIE ROZWIĄZAŃ ZADAŃ OTWARTYCH.")
    assert not common.has_real_content(None)


def test_author_gets_the_task_but_never_the_key_when_content_exists():
    prompt, source = generate.build_prompt(_task("Prostokąt o bokach 12 i 8. Oblicz pole."))
    assert source == "paper"
    assert "Oblicz pole" in prompt and "prostokąt 12 na 8" in prompt
    assert "ROZWIĄZANIE PRZYKŁADOWE" not in prompt


def test_author_reconstructs_from_the_key_when_content_is_a_placeholder():
    prompt, source = generate.build_prompt(_task("ZADANIE 18. ZNAJDUJE SIĘ NA KARCIE …"))
    assert source == "key"
    assert "P = 12 · 8 = 96" in prompt


def test_record_carries_provenance_and_empty_grading():
    generated = generate.Generated(task_text="Prostokąt 12 na 8, pole?", answers=[
        generate.Answer(kind="full", text="12·8=96 cm²", intent="poprawnie"),
        generate.Answer(kind="partial", text="12·8=86", intent="błąd rachunkowy"),
        generate.Answer(kind="wrong", text="20", intent="suma boków"),
    ])
    record = generate.record_for(_task(None), generated, "key", "openai:gpt-5.6-luna")
    assert record["content_source"] == "key"
    assert record["task_text"] == "Prostokąt 12 na 8, pole?"
    assert [a["author"] for a in record["answers"]] == ["model:openai:gpt-5.6-luna"] * 3
    assert all(a["grading"] is None for a in record["answers"])


def test_paper_content_wins_over_reconstruction():
    generated = generate.Generated(task_text="(model coś dopisał)", answers=[])
    record = generate.record_for(_task("Treść z zeszytu."), generated, "paper", "m")
    assert record["task_text"] == "Treść z zeszytu."


def test_schemas_are_strict():
    for model in (generate.Generated, grade.Grade):
        schema = strict_schema(model)
        assert schema["additionalProperties"] is False
        for name, obj in schema.get("$defs", {}).items():
            assert set(obj["required"]) == set(obj["properties"]), name


def test_golden_path_layout():
    assert common.golden_path(2025, "18").as_posix().endswith("golden/2025/task-18.json")
