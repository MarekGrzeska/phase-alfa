"""Runner migracji SQL — plain SQL, bez ORM.

Schemat bazy jest kontraktem między warstwą Pythona a warstwą C#, więc ma być
czytelny jako SQL, a nie wyprowadzalny z modelu w którymkolwiek języku.
C# ten schemat wyłącznie CZYTA i nigdy go nie zmienia.

Zasady:
  * jeden plik = jeden krok, wykonywany w JEDNEJ transakcji razem z wpisem
    do `schema_migrations` — migracja albo weszła w całości, albo wcale;
  * kolejność po nazwie pliku (`0001_`, `0002_`, ...);
  * migracja już zastosowana NIE MOŻE zmieniać treści — suma SHA-256 jest
    sprawdzana przy każdym uruchomieniu i rozjazd przerywa pracę;
  * uruchomienie na aktualnej bazie nie robi nic (idempotencja).

Użycie:
    uv run python ingest/schema/migrate.py            # zastosuj brakujące
    uv run python ingest/schema/migrate.py --status   # tylko pokaż stan
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:  # pragma: no cover - komunikat lepszy niż stack trace
    sys.exit("BRAK: psycopg. Uruchom `uv sync` w katalogu ingest/.")

KATALOG = Path(__file__).parent / "migrations"

TABELA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    wersja      text        PRIMARY KEY,
    zastosowano timestamptz NOT NULL DEFAULT now(),
    suma_sha256 char(64)    NOT NULL
)
"""


def polaczenie() -> str:
    """Connection string wyłącznie z konfiguracji — nigdy z kodu."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit(
            "BRAK: zmienna DATABASE_URL.\n"
            "Skopiuj .env.example do .env (albo ustaw ją w środowisku).\n"
            "Przykład: postgresql://klucz:klucz_dev@localhost:55432/klucz"
        )
    return url


def suma(sciezka: Path) -> str:
    """SHA-256 treści, po normalizacji zakończeń linii i BOM-u.

    Suma ma reagować na zmianę TREŚCI, a nie na to, czym plik był zapisany:

    * `utf-8-sig` zjada BOM — PowerShell na Windows dopisuje go przy
      `Set-Content -Encoding utf8` i bez tego niewinne otwarcie pliku
      w złym edytorze wyglądałoby jak podmiana migracji;
    * CRLF → LF, bo inaczej ta sama migracja ma inną sumę na Windows
      i na Linuksie w CI. `.gitattributes` to wymusza, ale runner nie ma
      prawa się na to ślepo zdawać.

    Czego celowo NIE normalizuje: samych znaków. Plik przepuszczony przez
    złe kodowanie (`·` → `Â·`) MA zerwać sumę — to jest uszkodzona migracja,
    nie kosmetyka.
    """
    tresc = sciezka.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    return hashlib.sha256(tresc.encode("utf-8")).hexdigest()


def migracje() -> list[tuple[str, Path, str]]:
    if not KATALOG.is_dir():
        sys.exit(f"BRAK katalogu migracji: {KATALOG}")
    pliki = sorted(KATALOG.glob("*.sql"))
    if not pliki:
        sys.exit(f"BRAK plików .sql w {KATALOG}")
    return [(p.stem, p, suma(p)) for p in pliki]


def zastosowane(cur) -> dict[str, str]:
    cur.execute("SELECT wersja, suma_sha256 FROM schema_migrations")
    return {w: s for w, s in cur.fetchall()}


def sprawdz_sumy(wszystkie, juz: dict[str, str]) -> None:
    """Migracja, która już weszła, nie może zmienić treści.

    Gdyby mogła, dwie maszyny z tą samą wersją schematu miałyby różne bazy —
    a schemat jest kontraktem.
    """
    for wersja, sciezka, sha in wszystkie:
        stare = juz.get(wersja)
        if stare is not None and stare != sha:
            sys.exit(
                f"ROZJAZD: migracja {wersja} została zmieniona po zastosowaniu.\n"
                f"  w bazie: {stare}\n"
                f"  w pliku: {sha}  ({sciezka})\n"
                "Zastosowanej migracji się nie edytuje — dopisz nową."
            )


def status(wszystkie, juz: dict[str, str]) -> int:
    brak = 0
    for wersja, _, _ in wszystkie:
        if wersja in juz:
            print(f"  [x] {wersja}")
        else:
            print(f"  [ ] {wersja}")
            brak += 1
    return brak


def main() -> int:
    ap = argparse.ArgumentParser(description="Migracje schematu korpusu")
    ap.add_argument("--status", action="store_true", help="tylko pokaż stan, nic nie zmieniaj")
    args = ap.parse_args()

    wszystkie = migracje()

    with psycopg.connect(polaczenie()) as conn:
        with conn.cursor() as cur:
            cur.execute(TABELA)
        conn.commit()

        with conn.cursor() as cur:
            juz = zastosowane(cur)

        sprawdz_sumy(wszystkie, juz)

        if args.status:
            brak = status(wszystkie, juz)
            print(f"\n{len(wszystkie) - brak}/{len(wszystkie)} zastosowanych.")
            return 0

        nowe = [(w, p, s) for w, p, s in wszystkie if w not in juz]
        if not nowe:
            print(f"Schemat aktualny — {len(wszystkie)} migracji, nic do zrobienia.")
            return 0

        for wersja, sciezka, sha in nowe:
            sql = sciezka.read_text(encoding="utf-8")
            # Jedna transakcja: DDL + wpis o nim. Migracja przerwana w połowie
            # nie zostawia bazy w stanie, którego nie da się nazwać.
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (wersja, suma_sha256) VALUES (%s, %s)",
                    (wersja, sha),
                )
            print(f"  + {wersja}")

        print(f"\nZastosowano {len(nowe)} migracji ({len(wszystkie)} razem).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
