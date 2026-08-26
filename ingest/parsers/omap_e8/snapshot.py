#!/usr/bin/env python3
"""Zrzut liczb parsera bez bazy — i porównanie dwóch zrzutów.

Reguła z planu A2 (G2.3.1, krok 3): po każdej poprawce parsera idzie przebieg
kontrolny wszystkich kluczy i porównanie z poprzednim. Poprawka dla rocznika
2019 nie ma prawa ruszyć wyników 2020–2026, a regresję taniej złapać na
raporcie niż na dwudziestu zadaniach w ekranie korekty.

Zrzut nie dotyka bazy celowo: pyta wyłącznie o to, co produkuje parser, więc
działa też wtedy, gdy korpus jest w połowie skorygowany i przebieg z ładowarką
pomijałby połowę kluczy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import warnings
from pathlib import Path

from parsers.omap_e8 import parser as K
from parsers.omap_e8.run import ROOT, base_variant, wiersze
from sciezki import KORZEN_REPO

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Liczby porównywane wiersz po wierszu. Skrót treści stoi obok nich, bo sama
# liczba kryteriów nie odróżnia „tyle samo progów" od „tyle samo progów o innym
# tekście" — a to drugie jest właśnie cichą regresją rekonstrukcji.
COUNTS = ("tasks", "points", "requirements", "answers", "criteria", "conditions",
          "expressions", "solutions", "rules", "notes")


def _digest(parts: list[str]) -> str:
    """SHA-256 sklejonych tekstów — reaguje na TREŚĆ, nie na kolejność bajtów."""
    joined = "\n".join(" ".join(p.split()) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def measure(key) -> dict:
    """Jeden klucz → liczby i skróty treści."""
    criteria = [c for z in key.zadania for c in z.kryteria]
    conditions = [w for c in criteria for w in c["warunki"]]
    expressions = [e for w in conditions for e in w["zapisy"]]
    return {
        "dialect": key.dialekt,
        "tasks": len(key.zadania),
        "points": sum(z.punkty for z in key.zadania),
        "requirements": sum(len(z.ogolne) + len(z.szczegolowe) for z in key.zadania),
        "answers": sum(len(v) for z in key.zadania for v in z.odpowiedzi.values()),
        "criteria": len(criteria),
        "conditions": len(conditions),
        "expressions": len(expressions),
        "solutions": sum(len(z.rozwiazania) for z in key.zadania),
        "rules": len(key.reguly),
        "notes": sum(len(z.uwagi) for z in key.zadania),
        "closed_without_criteria": sum(1 for z in key.zadania
                                       if z.typ == "zamkniete" and not z.kryteria),
        "open_without_criteria": sum(1 for z in key.zadania
                                     if z.typ != "zamkniete" and not z.kryteria),
        "conditions_digest": _digest([w["opis"] for w in conditions]),
        "expressions_digest": _digest(expressions),
        "warnings": list(key.ostrzezenia),
    }


def collect(codes: set, years: set, variants: set, limit: int | None,
            engine: str) -> dict:
    out: dict[str, dict] = {}
    rows = list(wiersze(codes, set(), years=years, variants=variants))
    if limit:
        rows = rows[:limit]
    for row in rows:
        path = os.path.join(ROOT, row["sciezka_lokalna"])
        if not os.path.exists(path):
            continue
        try:
            key = K.czytaj_klucz(path, silnik=engine)
        except Exception as e:
            out[row["plik"]] = {"error": f"{type(e).__name__}: {e}"}
            print(f"{row['plik'][:40]:<40} BŁĄD {type(e).__name__}")
            continue
        out[row["plik"]] = {"year": row["rocznik"],
                            "variant": base_variant(row["warianty"]),
                            **measure(key)}
        seen = out[row["plik"]]
        print(f"{row['plik'][:40]:<40} {key.dialekt:<10} zadań {seen['tasks']:3d}"
              f"  kryteriów {seen['criteria']:3d}  warunków {seen['conditions']:3d}")
    return out


def compare(old: dict, new: dict) -> list[str]:
    """Różnice między zrzutami — jedna linia na klucz, który się ruszył."""
    lines = []
    for name in sorted(set(old) | set(new)):
        before, after = old.get(name), new.get(name)
        if before is None:
            lines.append(f"  + {name}: klucz nowy w zrzucie")
            continue
        if after is None:
            lines.append(f"  - {name}: klucz zniknął ze zrzutu")
            continue
        changes = [f"{field} {before.get(field)}→{after.get(field)}"
                   for field in COUNTS if before.get(field) != after.get(field)]
        changes += [f"{field} zmieniony skrót" for field in
                    ("conditions_digest", "expressions_digest")
                    if before.get(field) != after.get(field)]
        if before.get("dialect") != after.get("dialect"):
            changes.insert(0, f"dialekt {before.get('dialect')}→{after.get('dialect')}")
        if changes:
            lines.append(f"  ~ {name}: " + ", ".join(changes))
    return lines


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["keys"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", default="OMAP", help="kody arkuszy po przecinku")
    ap.add_argument("--year", default="", help="roczniki po przecinku")
    ap.add_argument("--variant", default="", help="warianty po przecinku")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--engine", default="pdfplumber", choices=["pdfplumber", "pymupdf"])
    ap.add_argument("--out", default=None,
                    help="gdzie zapisać zrzut (domyślnie data/reports/parser-RRRR-MM-DD.json)")
    ap.add_argument("--baseline", default=None,
                    help="zrzut odniesienia — po przebiegu wypisz różnice wobec niego")
    ap.add_argument("--compare", nargs=2, metavar=("STARY", "NOWY"),
                    help="porównaj dwa gotowe zrzuty i nie parsuj niczego")
    args = ap.parse_args()

    if args.compare:
        lines = compare(_load(Path(args.compare[0])), _load(Path(args.compare[1])))
        print("\n".join(lines) if lines else "  bez różnic")
        return 1 if lines else 0

    for module in ("pdfplumber", "pdfminer", "pypdf"):
        warnings.filterwarnings("ignore", category=UserWarning, module=module)

    keys = collect({c.strip() for c in args.code.split(",") if c.strip()},
                   {y.strip() for y in args.year.split(",") if y.strip()},
                   {v.strip() for v in args.variant.split(",") if v.strip()},
                   args.limit, args.engine)
    if not keys:
        print("nic nie pasuje do filtra — sprawdź MIRROR_ROOT i --year/--variant")
        return 2

    out = Path(args.out or (KORZEN_REPO / "data" / "reports"
                            / f"parser-{time.strftime('%Y-%m-%d')}.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"keys": keys}, fh, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"\nZrzut zapisany: {out} (kluczy: {len(keys)})")

    if args.baseline:
        lines = compare(_load(Path(args.baseline)), keys)
        print(f"\nRÓŻNICE wobec {args.baseline}")
        print("\n".join(lines) if lines else "  bez różnic")
        return 1 if lines else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
