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
from urllib.parse import quote

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


CZESCI = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


def polaczenie() -> str:
    """Adres bazy — wyłącznie z konfiguracji, nigdy z kodu.

    Adres SKŁADANY z części, a nie wpisany w całości, bo numer portu stał
    wcześniej w `.env` dwa razy: raz dla Dockera, raz w środku gotowego adresu.
    Przy kolizji portów zmieniało się jedno z nich, drugie zostawało po staremu,
    a objaw — „baza nieosiągalna" — nie wskazywał na przyczynę.

    `DATABASE_URL` ma pierwszeństwo i służy do wskazania innej bazy niż
    deweloperska (tak robią testy runnera na bazie tymczasowej).
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    brakuje = [k for k in CZESCI if not os.environ.get(k)]
    if brakuje:
        sys.exit(
            f"BRAK zmiennych: {', '.join(brakuje)}.\n"
            "Skopiuj .env.example do .env (albo ustaw je w środowisku)."
        )

    return (
        f"postgresql://{quote(os.environ['DB_USER'])}:{quote(os.environ['DB_PASSWORD'])}"
        f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}/{os.environ['DB_NAME']}"
    )


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


def migracje(katalog: Path) -> list[tuple[str, Path, str]]:
    if not katalog.is_dir():
        sys.exit(f"BRAK katalogu migracji: {katalog}")
    pliki = sorted(katalog.glob("*.sql"))
    if not pliki:
        sys.exit(f"BRAK plików .sql w {katalog}")
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
    ap.add_argument(
        "--migrations",
        type=Path,
        default=KATALOG,
        help="katalog z plikami .sql (domyślnie obok tego skryptu); "
        "istnieje po to, żeby dało się sprawdzić runner na migracjach testowych",
    )
    args = ap.parse_args()

    wszystkie = migracje(args.migrations)

    # autocommit=True jest tu WARUNKIEM poprawności, nie optymalizacją.
    # Bez niego pierwsze zapytanie samo otwiera transakcję, a późniejsze
    # `conn.transaction()` zakłada wtedy PUNKT PRZYWRACANIA wewnątrz niej
    # zamiast nowej transakcji. Wszystkie migracje lądowałyby w jednej
    # wspólnej transakcji, a napis „+ 0001" pojawiałby się przed
    # jakimkolwiek zatwierdzeniem — czyli kłamał, gdy padnie migracja druga.
    with psycopg.connect(polaczenie(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(TABELA)

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
