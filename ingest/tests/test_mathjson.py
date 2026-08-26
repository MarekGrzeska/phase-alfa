"""Konwersja zapisów równoważnych na MathJSON (G2.6).

Dwie warstwy, dwa różne pytania. Normalizacja jest w Pythonie i chodzi
W KAŻDYM przebiegu CI — to w niej siedzą pułapki dokumentów CKE. Konwerter
w Node ma osobny test, utrwalony na tych samych parach, pomijany gdy Node'a
albo jego zależności nie ma: bramka ma mówić, czego NIE sprawdziła.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

from mathjson import fill, normalize

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
RECORDED = os.path.join(FIXTURES, "mathjson-2026-08-26.json")


@pytest.fixture(scope="module")
def pairs() -> list[dict]:
    with open(RECORDED, encoding="utf-8") as fh:
        return json.load(fh)["pary"]


# ── normalizacja: pułapki dokumentu, sprawdzane bez Node'a ──────────────────

@pytest.mark.parametrize(("expression", "expected"), [
    ("12∶3", r"12 \div 3"),                       # ∶ (U+2236) to dzielenie CKE
    ("V=1/3∙9∙9∙H", r"V=\frac{1}{3} \cdot 9 \cdot 9 \cdot H"),
    ("P_(AECF)=7/15", r"P_{AECF}=\frac{7}{15}"),  # indeks po scaleniu serii
    ("k^(-10)", r"k^{-10}"),                      # wykładnik -10 to JEDNA wartość
    ("40%∙120", r"40\% \cdot 120"),
    ("0,25", "0.25"),                             # przecinek dziesiętny
])
def test_normalisation_of_document_traps(expression, expected):
    assert normalize.to_latex(expression) == (expected, None)


def test_a_unit_does_not_break_into_a_fraction():
    """`60 min/40 min` czytało się jako `mi` + ułamek `n/40` — pół jednostki."""
    latex, why = normalize.to_latex("60 min/40 min")

    assert why is None
    assert r"\frac{n}" not in latex


def test_polish_tail_is_dropped_and_the_expression_stays():
    assert normalize.to_latex("2/5x+1/3x=440 lub zapisy równoważne") == (
        r"\frac{2}{5}x+\frac{1}{3}x=440", None)


def test_a_sentence_does_not_pose_as_an_expression():
    """„zapisanie P=15" to iloczyn dziewięciu symboli — poprawny i bezwartościowy.

    Bez tego sita status byłby `auto`, czyli błąd CICHY: w korpusie stoi
    MathJSON, w ekranie korekty nie ma czego poprawiać, a A3 dostaje śmieć.
    """
    latex, why = normalize.to_latex("zapisanie P=15 AECF")

    assert latex is None
    assert "tekst" in why


def test_a_root_refuses_on_purpose():
    """Decyzja G2.3.2: zasięg pierwiastka zostaje ręcznej korekcie."""
    latex, why = normalize.to_latex("√16+9")

    assert latex is None
    assert "G2.3.2" in why


def test_recorded_pairs_keep_the_same_normalisation(pairs):
    """Fixture jest kontraktem: zmiana normalizacji ma być widoczna w diffie."""
    assert pairs, "pusty fixture — test przechodziłby o niczym"
    for pair in pairs:
        assert normalize.to_latex(pair["expression"])[0] == pair["latex"], (
            f"zmieniła się normalizacja zapisu {pair['expression']!r}")


# ── konwerter w Node: osobny test, pomijany gdy nie ma czym ─────────────────

def _converter_missing() -> str:
    if shutil.which("node") is None:
        return "brak node — konwerter MathJSON go wymaga"
    if not (fill.HERE / "node_modules").exists():
        return "brak zaleznosci konwertera: pnpm -C ingest/mathjson install"
    return ""


@pytest.mark.skipif(bool(_converter_missing()), reason=_converter_missing())
def test_converter_returns_the_recorded_mathjson(pairs):
    """Jeden przebieg Node'a na cały fixture — start procesu kosztuje ~200 ms."""
    records = [{"id": i, "latex": p["latex"]}
               for i, p in enumerate(pairs) if p["latex"] is not None]
    assert records, "fixture bez ani jednego zapisu do konwersji"

    process = subprocess.run(
        ["node", str(fill.CONVERTER)],
        input="\n".join(json.dumps(r, ensure_ascii=False) for r in records),
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(fill.HERE), check=True,
    )
    out = {json.loads(line)["id"]: json.loads(line)
             for line in process.stdout.splitlines() if line.strip()}

    for i, pair in enumerate(pairs):
        if pair["latex"] is None:
            continue
        given = out[i]
        if pair.get("error"):
            assert "error" in given, f"{pair['expression']!r} miał się nie udać"
        else:
            assert given.get("mathjson") == pair["mathjson"], (
                f"Compute Engine zmienił wynik dla {pair['expression']!r}")


@pytest.mark.skipif(bool(_converter_missing()), reason=_converter_missing())
def test_converter_reports_an_error_instead_of_guessing():
    """Rozjechany zapis ma dać `error`, nie MathJSON z sufitu."""
    process = subprocess.run(
        ["node", str(fill.CONVERTER)],
        input=json.dumps({"id": 1, "latex": r"12= \cdot a"}) + "\n",
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(fill.HERE), check=True,
    )

    assert "error" in json.loads(process.stdout.strip())
