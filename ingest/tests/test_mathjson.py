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
UTRWALONE = os.path.join(FIXTURES, "mathjson-2026-08-26.json")


@pytest.fixture(scope="module")
def pary() -> list[dict]:
    with open(UTRWALONE, encoding="utf-8") as fh:
        return json.load(fh)["pary"]


# ── normalizacja: pułapki dokumentu, sprawdzane bez Node'a ──────────────────

@pytest.mark.parametrize(("zapis", "oczekiwany"), [
    ("12∶3", r"12 \div 3"),                       # ∶ (U+2236) to dzielenie CKE
    ("V=1/3∙9∙9∙H", r"V=\frac{1}{3} \cdot 9 \cdot 9 \cdot H"),
    ("P_(AECF)=7/15", r"P_{AECF}=\frac{7}{15}"),  # indeks po scaleniu serii
    ("k^(-10)", r"k^{-10}"),                      # wykładnik -10 to JEDNA wartość
    ("40%∙120", r"40\% \cdot 120"),
    ("0,25", "0.25"),                             # przecinek dziesiętny
])
def test_normalizacja_pulapek(zapis, oczekiwany):
    assert normalize.to_latex(zapis) == (oczekiwany, None)


def test_jednostka_nie_rozpada_sie_na_ulamek():
    """`60 min/40 min` czytało się jako `mi` + ułamek `n/40` — pół jednostki."""
    latex, why = normalize.to_latex("60 min/40 min")

    assert why is None
    assert r"\frac{n}" not in latex


def test_ogon_po_polsku_odpada_a_wyrazenie_zostaje():
    assert normalize.to_latex("2/5x+1/3x=440 lub zapisy równoważne") == (
        r"\frac{2}{5}x+\frac{1}{3}x=440", None)


def test_zdanie_nie_udaje_wyrazenia():
    """„zapisanie P=15" to iloczyn dziewięciu symboli — poprawny i bezwartościowy.

    Bez tego sita status byłby `auto`, czyli błąd CICHY: w korpusie stoi
    MathJSON, w ekranie korekty nie ma czego poprawiać, a A3 dostaje śmieć.
    """
    latex, why = normalize.to_latex("zapisanie P=15 AECF")

    assert latex is None
    assert "tekst" in why


def test_pierwiastek_odmawia_swiadomie():
    """Decyzja G2.3.2: zasięg pierwiastka zostaje ręcznej korekcie."""
    latex, why = normalize.to_latex("√16+9")

    assert latex is None
    assert "G2.3.2" in why


def test_utrwalone_pary_maja_te_sama_normalizacje(pary):
    """Fixture jest kontraktem: zmiana normalizacji ma być widoczna w diffie."""
    assert pary, "pusty fixture — test przechodziłby o niczym"
    for para in pary:
        assert normalize.to_latex(para["expression"])[0] == para["latex"], (
            f"zmieniła się normalizacja zapisu {para['expression']!r}")


# ── konwerter w Node: osobny test, pomijany gdy nie ma czym ─────────────────

def _konwerter_dostepny() -> str:
    if shutil.which("node") is None:
        return "brak node — konwerter MathJSON go wymaga"
    if not (fill.HERE / "node_modules").exists():
        return "brak zaleznosci konwertera: pnpm -C ingest/mathjson install"
    return ""


@pytest.mark.skipif(bool(_konwerter_dostepny()), reason=_konwerter_dostepny())
def test_konwerter_oddaje_utrwalony_mathjson(pary):
    """Jeden przebieg Node'a na cały fixture — start procesu kosztuje ~200 ms."""
    wejscie = [{"id": i, "latex": p["latex"]}
               for i, p in enumerate(pary) if p["latex"] is not None]
    assert wejscie, "fixture bez ani jednego zapisu do konwersji"

    proces = subprocess.run(
        ["node", str(fill.CONVERTER)],
        input="\n".join(json.dumps(r, ensure_ascii=False) for r in wejscie),
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(fill.HERE), check=True,
    )
    wynik = {json.loads(line)["id"]: json.loads(line)
             for line in proces.stdout.splitlines() if line.strip()}

    for i, para in enumerate(pary):
        if para["latex"] is None:
            continue
        oddane = wynik[i]
        if para.get("error"):
            assert "error" in oddane, f"{para['expression']!r} miał się nie udać"
        else:
            assert oddane.get("mathjson") == para["mathjson"], (
                f"Compute Engine zmienił wynik dla {para['expression']!r}")


@pytest.mark.skipif(bool(_konwerter_dostepny()), reason=_konwerter_dostepny())
def test_konwerter_zglasza_blad_zamiast_zgadywac():
    """Rozjechany zapis ma dać `error`, nie MathJSON z sufitu."""
    proces = subprocess.run(
        ["node", str(fill.CONVERTER)],
        input=json.dumps({"id": 1, "latex": r"12= \cdot a"}) + "\n",
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(fill.HERE), check=True,
    )

    assert "error" in json.loads(proces.stdout.strip())
