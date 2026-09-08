"""Inspektor danych — każda tabela, każdy wiersz, i skąd się wziął.

Narzędzie tylko do ODCZYTU, obok ekranu korekty w tej samej aplikacji: to jedyne
miejsce w projekcie, które naraz widzi wszystkie statusy (nie tylko korpus), ma
pod ręką PDF-y z mirrora i wycinki z bloba. Aplikacja React tego nie może — nie
wolno jej otworzyć PDF-a.

Trzy rzeczy, których się tu pilnuje:

- nazwy tabel i kolumn NIGDY nie idą z adresu do SQL-a wprost — tylko przez
  allowlistę z `information_schema` i `sql.Identifier`;
- „źródło" kolumny to wiedza o KODZIE (kto ją pisze), nie o WIERSZU. Tam, gdzie
  schemat niesie pochodzenie per wiersz (`reviewed_by`, `description_status`,
  `mathjson_status`), inspektor mówi to osobno i wprost;
- plik, na który wskazuje baza, może nie leżeć na dysku — to jest inny stan niż
  NULL i inspektor ma go pokazywać, bo to właśnie błąd danych do wyłapania.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlencode

import psycopg
from psycopg import sql

from correction import pages
from pdf import crop as crop_pdf

PER_PAGE_OPTIONS = (25, 50, 100)
PER_PAGE = 50
# Wybór zapamiętuje CIASTECZKO, a nie `localStorage`: ustawia je serwer przy
# przekierowaniu, więc ekran nie potrzebuje do tego ani linijki JavaScriptu.
PER_PAGE_COOKIE = "inspect_per"
PER_PAGE_MAX_AGE = 365 * 24 * 3600
CHILD_PREVIEW = 8


def per_page_or_default(raw: str | None) -> int:
    """Rozmiar strony z adresu albo ciasteczka; cokolwiek innego to wartość domyślna."""
    if raw and raw.isdigit() and int(raw) in PER_PAGE_OPTIONS:
        return int(raw)
    return PER_PAGE


# ------------------------------------------------------------------ schemat

@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool
    default: str | None


@dataclass
class Table:
    name: str
    columns: list[Column]
    primary_key: list[str]
    # kolumna → (tabela nadrzędna, kolumna nadrzędna)
    parents: dict[str, tuple[str, str]] = field(default_factory=dict)
    # (tabela potomna, kolumna potomna) wskazujące na ten wiersz
    children: list[tuple[str, str]] = field(default_factory=list)

    @property
    def single_key(self) -> str | None:
        return self.primary_key[0] if len(self.primary_key) == 1 else None

    def has_column(self, name: str) -> bool:
        return any(c.name == name for c in self.columns)


@dataclass
class Schema:
    tables: dict[str, Table]
    views: list[str]
    # tabela → kolumna → wartości dopuszczone więzem CHECK
    enums: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def __contains__(self, name: str) -> bool:
        return name in self.tables


# `CHECK ((kind = ANY (ARRAY['closed'::text, 'open_short'::text])))` — tak PostgreSQL
# normalizuje `IN (...)`. Więzy zakresowe (`max_points >= 0 AND <= 60`) i międzykolumnowe
# (`finished_at >= started_at`) nie pasują do tego wzorca i mają nie pasować.
_CHECK_ENUM = re.compile(r"^CHECK \(\((\w+) = ANY \(ARRAY\[(.+)\]\)\)\)$")
_ENUM_VALUE = re.compile(r"'((?:[^']|'')*)'::\w+")


def load_enums(cur) -> dict[str, dict[str, list[str]]]:
    """Wartości dopuszczone przez więzy CHECK — słownik prosto ze schematu.

    Źródłem jest schemat, a nie `SELECT DISTINCT`: status, którego dziś nie ma
    ani w jednym wierszu, wciąż jest legalną wartością i ma dać się wybrać.
    """
    cur.execute(
        """SELECT rel.relname AS table_name, pg_get_constraintdef(con.oid) AS definition
           FROM pg_constraint con
           JOIN pg_class rel ON rel.oid = con.conrelid
           JOIN pg_namespace n ON n.oid = rel.relnamespace
           WHERE con.contype = 'c' AND n.nspname = 'public'"""
    )
    out: dict[str, dict[str, list[str]]] = {}
    for row in cur.fetchall():
        found = _CHECK_ENUM.match(row["definition"])
        if found is None:
            continue
        values = [v.replace("''", "'") for v in _ENUM_VALUE.findall(found.group(2))]
        if values:
            out.setdefault(row["table_name"], {})[found.group(1)] = values
    return out


def load_schema(cur) -> Schema:
    """Allowlista tabel, kolumn i kluczy obcych — prosto z katalogu bazy.

    To, a nie ręczna lista, jest źródłem prawdy: migracja dokładająca kolumnę
    ma być widoczna w inspektorze bez dotykania tego pliku.
    """
    cur.execute(
        """SELECT table_name, column_name, data_type, is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name IN (SELECT table_name FROM information_schema.tables
                                WHERE table_schema = 'public' AND table_type = 'BASE TABLE')
           ORDER BY table_name, ordinal_position"""
    )
    tables: dict[str, Table] = {}
    for row in cur.fetchall():
        table = tables.setdefault(row["table_name"], Table(row["table_name"], [], []))
        table.columns.append(Column(row["column_name"], row["data_type"],
                                    row["is_nullable"] == "YES", row["column_default"]))

    cur.execute(
        """SELECT tc.table_name, kcu.column_name, tc.constraint_type,
                  ccu.table_name AS ref_table, ccu.column_name AS ref_column
           FROM information_schema.table_constraints tc
           JOIN information_schema.key_column_usage kcu
             ON kcu.constraint_name = tc.constraint_name
            AND kcu.table_schema = tc.table_schema
           LEFT JOIN information_schema.constraint_column_usage ccu
             ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
           WHERE tc.table_schema = 'public'
             AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
           ORDER BY tc.table_name, kcu.ordinal_position"""
    )
    for row in cur.fetchall():
        table = tables.get(row["table_name"])
        if table is None:
            continue
        if row["constraint_type"] == "PRIMARY KEY":
            table.primary_key.append(row["column_name"])
        elif row["ref_table"] in tables:
            table.parents[row["column_name"]] = (row["ref_table"], row["ref_column"])
            tables[row["ref_table"]].children.append((table.name, row["column_name"]))

    cur.execute(
        """SELECT table_name FROM information_schema.views
           WHERE table_schema = 'public' ORDER BY table_name"""
    )
    views = [r["table_name"] for r in cur.fetchall()]
    return Schema(tables, views, load_enums(cur))


_SCHEMA: dict[str, Schema] = {}


def schema(cur) -> Schema:
    """Schemat czytany raz na wersję migracji — zmienia się tylko migracją.

    Kluczem jest ostatnia zastosowana migracja, nie proces: testy stawiają bazę
    od nowa w tym samym procesie, a `--reload` uvicorna nie jest gwarancją.
    """
    cur.execute("SELECT max(version) AS v FROM schema_migrations")
    stamp = (cur.fetchone() or {}).get("v") or ""
    if stamp not in _SCHEMA:
        _SCHEMA.clear()
        _SCHEMA[stamp] = load_schema(cur)
    return _SCHEMA[stamp]


# ------------------------------------------------------ źródło każdej kolumny

# Kto pisze kolumnę — wiedza o KODZIE, spisana z każdego INSERT/UPDATE w repozytorium
# (docs/database-guide.html, sekcja 04). Etykieta „nikt" to kolumna, którą schemat
# obiecuje, a żaden przebieg dziś nie wypełnia — celowo widoczna, nie ukryta.
SOURCES: dict[str, dict[str, str]] = {
    "requirement_regime": {
        "code": "parser", "name": "parser", "session_from": "ładowarka",
        "session_to": "nikt", "source": "parser",
    },
    "requirement": {
        "regime_id": "ładowarka", "parent_id": "nikt", "kind": "ładowarka",
        "stage": "parser", "path": "parser", "content": "parser",
    },
    "document": {
        "segment": "urls.tsv", "year": "urls.tsv", "code": "urls.tsv", "variants": "urls.tsv",
        "session": "parser", "kind": "ładowarka", "kind_source": "urls.tsv", "url": "urls.tsv",
        "path": "urls.tsv", "sha256": "nikt", "pages": "parser", "ingest_status": "ekran",
    },
    "exam_form": {
        "regime_id": "ładowarka", "exam": "parser", "subject": "urls.tsv", "code": "parser",
        "variant": "parser", "version": "parser", "session": "parser",
    },
    "exam_form_document": {
        "exam_form_id": "ładowarka", "document_id": "ładowarka", "role": "ładowarka",
    },
    "task": {
        "marking_scheme_id": "ładowarka", "number": "parser · ekran", "position": "parser",
        "max_points": "parser · ekran", "kind": "parser · ekran", "page": "parser",
        "review_status": "ekran · verify", "reviewed_at": "ekran · verify",
        "reviewed_by": "ekran · verify", "review_model": "verify",
    },
    "task_requirement": {"task_id": "ładowarka · ekran", "requirement_id": "ładowarka · ekran"},
    "task_version": {
        "task_id": "ładowarka", "exam_form_id": "ładowarka", "paper_id": "ładowarka",
        "content": "parser zeszytu · ekran", "content_status": "nikt (zawsze auto)",
        "page": "parser", "bbox": "nikt",
    },
    "model_answer": {"task_version_id": "ładowarka", "part": "parser", "answer": "parser · ekran"},
    "criterion": {
        "task_id": "ładowarka · ekran", "points": "parser · ekran", "label": "parser · ekran",
        "description": "parser · ekran", "position": "parser",
    },
    "criterion_condition": {
        "criterion_id": "ładowarka · ekran", "description": "parser · ekran",
        "position": "ładowarka",
    },
    "condition_expression": {
        "condition_id": "ładowarka · ekran", "expression": "parser · ekran",
        "mathjson": "mathjson", "mathjson_status": "mathjson · ekran",
        "mathjson_error": "mathjson", "position": "ładowarka",
    },
    "example_solution": {
        "task_id": "ładowarka", "points": "parser", "method": "parser",
        "content": "parser", "position": "parser",
    },
    "answer_example": {
        "task_id": "nikt", "content": "nikt", "accepted": "nikt", "justification": "nikt",
    },
    "rule": {
        "marking_scheme_id": "ładowarka", "kind": "parser", "content": "parser",
        "tasks_from": "parser", "tasks_to": "parser", "position": "ładowarka",
    },
    "asset": {
        "task_version_id": "ładowarka", "kind": "detektor", "path": "ładowarka",
        "page": "detektor · ekran", "bbox": "detektor · frame · ekran",
        "description": "describe · ekran", "description_status": "describe · ekran",
    },
    "correction_event": {
        "task_id": "decide", "action": "decide", "started_at": "ekran (zegar hosta)",
        "finished_at": "baza", "fields_changed": "db.save", "actor": "decide",
        "model": "verify",
    },
    "prefill_suggestion": {
        "task_id": "prefill", "model": "prefill", "payload": "prefill",
        "input_tokens": "llm.py", "output_tokens": "llm.py", "batch": "prefill",
        "created_at": "baza",
    },
    "schema_migrations": {"version": "migrate.py", "applied_at": "baza", "sha256": "migrate.py"},
}

TABLE_NOTES: dict[str, str] = {
    "requirement_regime": "Reżim wymagań — wisi na sesji egzaminu, nie na roku pliku.",
    "requirement": "Wymagania podstawy; drzewo dziś płaskie (parent_id nikt nie pisze).",
    "document": "Jeden wiersz = jeden PDF w mirrorze, kolumny lustrzane wobec urls.tsv.",
    "exam_form": "Forma arkusza: variant to dostosowanie, version to bliźniak X/Y.",
    "exam_form_document": "N:M — jeden klucz obsługuje do sześciu form.",
    "task": "Jednostka logiczna; kryteria wiszą tu, odpowiedzi na wersji. Status = bramka.",
    "task_requirement": "Zadanie ↔ wymagania, N:M.",
    "task_version": "Konkretna treść w konkretnej formie; tu mieszka to, co różni bliźniaki.",
    "model_answer": "Odpowiedź wzorcowa zadania zamkniętego — na wersji, bo X i Y się różnią.",
    "criterion": "Próg punktowy. UNIQUE (task_id, points) jest ostry celowo.",
    "criterion_condition": "Warunek progu — alternatywa („LUB”).",
    "condition_expression": "Zapis równoważny wewnątrz warunku („albo”); MathJSON obok.",
    "example_solution": "„I sposób”, „II sposób” z klucza; ekran tego nie edytuje.",
    "answer_example": "Pod klucze z angielskiego. Parser matematyki tu nie pisze — 0 wierszy.",
    "rule": "„Uwagi ogólne” — reguły arkusza, działają w kroku Compose. Wiszą na dokumencie.",
    "asset": "Wycinek graficzny; wisi na wersji. Pięć procesów pisze do tej tabeli.",
    "correction_event": "Dziennik bramki; task_id ON DELETE SET NULL, żeby pomiar przeżył reload.",
    "prefill_suggestion": "Propozycja modelu OBOK korpusu — nie dotyka criterion.",
    "schema_migrations": "Zakłada ją runner, nie migracja. SHA-256 pilnuje treści plików.",
}

# Kolumny do streszczenia wiersza w listach i w podglądzie dzieci.
SUMMARY: dict[str, tuple[str, ...]] = {
    "document": ("kind", "code", "variants", "session", "path"),
    "exam_form": ("code", "variant", "version", "session"),
    "task": ("number", "max_points", "kind", "review_status", "reviewed_by"),
    "task_version": ("exam_form_id", "page", "content"),
    "model_answer": ("part", "answer"),
    "criterion": ("points", "label", "description"),
    "criterion_condition": ("position", "description"),
    "condition_expression": ("position", "expression", "mathjson_status"),
    "example_solution": ("points", "method", "content"),
    "rule": ("kind", "tasks_from", "tasks_to", "content"),
    "asset": ("kind", "page", "description_status", "path"),
    "requirement": ("kind", "stage", "path", "content"),
    "requirement_regime": ("code", "name", "session_from"),
    "correction_event": ("action", "actor", "model", "finished_at"),
    "prefill_suggestion": ("model", "batch", "created_at"),
    "task_requirement": ("task_id", "requirement_id"),
    "exam_form_document": ("exam_form_id", "document_id", "role"),
    "answer_example": ("accepted", "content"),
    "schema_migrations": ("version", "applied_at"),
}


def source_of(table: str, column: str) -> str:
    if column == "id":
        return "sekwencja"
    return SOURCES.get(table, {}).get(column, "?")


def row_provenance(table: str, row: dict) -> list[str]:
    """Pochodzenie TEGO wiersza — tylko tam, gdzie schemat je naprawdę niesie."""
    notes: list[str] = []
    if table == "task":
        status = row.get("review_status")
        if status == "pending":
            notes.append("nierozstrzygnięte — poza korpusem; wartości prosto z parsera")
        else:
            who = row.get("reviewed_by")
            model = row.get("review_model")
            notes.append(f"{status}: rozstrzygnął {who}"
                         + (f" ({model})" if model else "") + f" — {row.get('reviewed_at')}")
            if status == "corrected":
                notes.append("co najmniej jedna kolumna tego zadania albo jego dzieci "
                             "została zmieniona po parserze — które, mówi correction_event")
    elif table == "asset":
        status = row.get("description_status")
        labels = {
            "none": "opisu nie ma", "auto": "opis napisał model (task describe)",
            "approved": "opis modelu przyjęty przez człowieka bez zmian",
            "corrected": "opis modelu poprawiony przez człowieka",
            "manual": "opis napisany od zera przez człowieka — poza pomiarem S7",
        }
        notes.append(labels.get(status, str(status)))
        if row.get("bbox") and float(row["bbox"][0]) == 0 and float(row["bbox"][1]) == 0:
            notes.append("ramka zaczyna się w rogu strony — to „cała strona”, nie rysunek")
    elif table == "condition_expression":
        status = row.get("mathjson_status")
        labels = {
            "none": "konwerter jeszcze nie próbował", "auto": "MathJSON z konwertera",
            "approved": "MathJSON potwierdzony przez człowieka — konwerter go nie nadpisze",
            "failed": f"konwerter odmówił: {row.get('mathjson_error') or '—'}",
        }
        notes.append(labels.get(status, str(status)))
    elif table == "task_version":
        notes.append("treść z zeszytu zadań" if row.get("paper_id")
                     else "brak zeszytu w bazie — treść NULL, strona to strona klucza")
    elif table == "correction_event":
        notes.append(f"{row.get('action')} przez {row.get('actor')}"
                     + (f" ({row.get('model')})" if row.get("model") else ""))
        if row.get("task_id") is None:
            notes.append("sierota: zadanie skasowane przy przeładowaniu klucza, "
                         "wiersz został dla pomiaru S8")
    elif table == "document":
        notes.append(f"typ rozpoznany po: {row.get('kind_source')}")
    return notes


# ----------------------------------------------------------------- zapytania

def _table(sch: Schema, name: str) -> Table:
    if name not in sch:
        raise KeyError(name)
    return sch.tables[name]


def table_size(cur, name: str) -> int:
    """Wierszy w tabeli, bez filtru — wejście dla rozpoznania kolumny słownikowej."""
    cur.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(name)))
    return cur.fetchone()["n"]


def counts(cur, sch: Schema) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in sch.tables:
        cur.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(name)))
        out[name] = cur.fetchone()["n"]
    return out


# --------------------------------------------------------- filtry i sortowanie

# Parametry adresu, które NIE są filtrem. Podkreślnik na początku, bo bez niego
# kolidują z nazwami kolumn: `task.page` i `asset.page` istnieją naprawdę, więc
# `?page=11` znaczyło „strona 11" i po tej kolumnie nie dało się filtrować wcale,
# a wiersz filtrów wysyłał `page=` i cała lista wracała z 422.
RESERVED_PARAMS = frozenset({"_page", "_sort", "_dir", "_cols", "_per"})

# Wiersz filtrów pod nagłówkami przysyła wartość pod nazwą kolumny, a wybrany
# operator obok, pod `op.<kolumna>`. Osobny prefiks, a nie sufiks przy kolumnie,
# bo `kolumna__op` kolidowałoby z kanonicznym `kolumna__operator`.
OPERATOR_PREFIX = "op."

# Operator → (znak w wierszu filtrów, nazwa dla człowieka, czy potrzebuje wartości).
OPERATORS: dict[str, tuple[str, str, bool]] = {
    "eq": ("=", "=", True),
    "ne": ("≠", "≠", True),
    "contains": ("≈", "zawiera", True),
    "gt": (">", ">", True),
    "gte": ("≥", "≥", True),
    "lt": ("<", "<", True),
    "lte": ("≤", "≤", True),
    "null": ("∅", "jest pusta", False),
    "notnull": ("!∅", "nie jest pusta", False),
}

# Domyślny operator wiersza filtrów zależy od typu: po tekście szuka się fragmentu,
# po liczbie, dacie i kluczu obcym — konkretnej wartości.
TEXT_TYPES = frozenset({"text", "character varying", "character"})

# Porównania idą po TYPIE KOLUMNY, nie po tekście: '9' > '10' jest prawdą dla
# napisów i fałszem dla liczb, a `points > 2` ma znaczyć to drugie. Równość
# zostaje na `::text`, bo ten sam mechanizm obsługuje wtedy jsonb i tablice.
_COMPARISONS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}

# Ile różnych wartości kolumny wystarczy, żeby podpowiadać je listą zamiast
# kazać wpisywać z pamięci.
SUGGEST_LIMIT = 25
SUGGEST_COLUMNS = 14


class FilterError(Exception):
    """Filtr, którego baza nie przyjmuje — np. tekst w porównaniu liczbowym."""


@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: str | None

    @property
    def param(self) -> str:
        """Nazwa w adresie. `eq` bez sufiksu — linki z widoku wiersza tak wyglądają."""
        return self.column if self.op == "eq" else f"{self.column}__{self.op}"

    @property
    def label(self) -> str:
        text = f"{self.column} {OPERATORS[self.op][1]}"
        return f"{text} {self.value}" if OPERATORS[self.op][2] else text


# Typy, po których da się sensownie porównywać `>` i `<`. Reszta (jsonb, tablice)
# dostaje traktowanie tekstowe: `bbox > 5` nie znaczy nic, `bbox zawiera 0` znaczy.
ORDERED_TYPES = frozenset({
    "smallint", "integer", "bigint", "numeric", "real", "double precision",
    "date", "timestamp with time zone", "timestamp without time zone",
})

# Powyżej tej długości wartość przestaje nadawać się do listy rozwijanej —
# dwadzieścia akapitów treści kryterium to nie jest słownik.
ENUM_VALUE_LENGTH = 40

# Słownikiem czyni kolumnę POWTARZALNOŚĆ wartości, a nie ich mała liczba: przy
# trzech wierszach w tabeli każda kolumna ma mało różnych wartości i każda
# wyglądałaby na słownik. Więz CHECK jest od tego wolny — tam wartości daje schemat.
DICTIONARY_MIN_ROWS = 20
DICTIONARY_REPEAT = 4


def default_op(column: Column) -> str:
    return "contains" if column.type in TEXT_TYPES else "eq"


@dataclass
class ColumnFilter:
    """Jak wygląda filtr JEDNEJ kolumny: lista wartości albo wpisywanie."""
    column: Column
    options: list[str] | None
    operators: list[str]
    default: str

    @property
    def is_enum(self) -> bool:
        return self.options is not None


def column_filters(table: Table, enums: dict[str, list[str]],
                   hints: dict[str, list[str]], rows: int = 0) -> dict[str, ColumnFilter]:
    """Opis wiersza filtrów. Kolumna słownikowa dostaje listę, nie pole tekstowe.

    Słownikiem jest kolumna z więzem CHECK (wartości ze schematu, komplet),
    kolumna logiczna oraz taka, której dane wyraźnie się powtarzają. Wpisywanie
    zostaje tam, gdzie zbiór wartości jest otwarty: treści, ścieżki, liczby, daty.
    """
    out: dict[str, ColumnFilter] = {}
    for column in table.columns:
        options = enums.get(column.name)
        if options is None and column.type == "boolean":
            options = ["true", "false"]
        if options is None and rows >= DICTIONARY_MIN_ROWS:
            data = hints.get(column.name)
            if (data and len(data) * DICTIONARY_REPEAT <= rows
                    and all(len(v) <= ENUM_VALUE_LENGTH for v in data)):
                options = data

        if options is not None:
            operators, default = ["eq", "ne"], "eq"
        elif column.type in ORDERED_TYPES:
            operators, default = ["eq", "ne", "gt", "gte", "lt", "lte"], "eq"
        else:
            operators, default = ["contains", "eq", "ne"], "contains"
        if column.nullable:
            operators = [*operators, "null", "notnull"]
        out[column.name] = ColumnFilter(column, options, operators, default)
    return out


def offer(described: ColumnFilter, active: Filter | None) -> ColumnFilter:
    """Filtr z adresu bywa szerszy niż to, co oferuje wiersz — ma przeżyć render.

    Bez tego `?kind__contains=clo` wpisane ręcznie gubiłoby operator przy pierwszym
    kliknięciu „Filtruj", bo wybrana opcja nie istniałaby na liście.
    """
    if active is None:
        return described
    operators = described.operators
    if active.op not in operators:
        operators = [active.op, *operators]
    options = described.options
    if options is not None and active.value is not None and active.value not in options:
        options = [active.value, *options]
    if operators is described.operators and options is described.options:
        return described
    return ColumnFilter(described.column, options, operators, described.default)


def parse_filters(table: Table, items) -> tuple[list[Filter], list[str], bool]:
    """Pary z adresu → filtry. Trzecia wartość: czy przyszły z wiersza filtrów.

    Dwie postacie znaczą to samo. Kanoniczna `kolumna__operator=wartość` (bez
    sufiksu = równość) jest w linkach i w pasku adresu. Formularzowa —
    `kolumna=wartość` plus `op.kolumna=operator` — bierze się stąd, że pole
    w wierszu filtrów nie umie samo zmienić swojej nazwy bez JavaScriptu.
    Trasa przemienia drugą na pierwszą i przekierowuje.

    Odrzucone NIE są po cichu pomijane: filtr, który nie działa, ale wygląda
    jakby działał, jest gorszy od błędu — pokazywałby pełną tabelę jako wynik.
    """
    pairs = list(items)
    chosen = {k[len(OPERATOR_PREFIX):]: v for k, v in pairs if k.startswith(OPERATOR_PREFIX)}
    # Sam fakt, że przyszły operatory, znaczy „to jest formularz": adres ma wtedy
    # zostać przepisany na kanoniczny także wtedy, gdy WSZYSTKIE pola są puste —
    # czyli gdy filtry właśnie zdjęto.
    from_form = bool(chosen)

    filters: list[Filter] = []
    rejected: list[str] = []
    for key, raw in pairs:
        if key in RESERVED_PARAMS or key.startswith(OPERATOR_PREFIX):
            continue
        column, _, suffix = key.partition("__")
        if not table.has_column(column):
            rejected.append(key)
            continue
        op = suffix or chosen.get(column) or "eq"
        if op not in OPERATORS:
            rejected.append(key)
            continue
        if OPERATORS[op][2]:
            if raw == "":
                continue
            filters.append(Filter(column, op, raw))
        else:
            filters.append(Filter(column, op, None))

    # „∅" i „niepusta" wybrane przy pustym polu — filtr bez wartości, którego
    # pętla wyżej nie zobaczy, jeśli przeglądarka nie przyśle pola w ogóle.
    for column, op in chosen.items():
        if not table.has_column(column) or op not in OPERATORS or OPERATORS[op][2]:
            continue
        if not any(f.column == column and f.op == op for f in filters):
            filters.append(Filter(column, op, None))
    return filters, rejected, from_form


def _where(filters: list[Filter]) -> tuple[sql.Composable, list[str]]:
    parts: list[sql.Composable] = []
    params: list[str] = []
    for f in filters:
        column = sql.Identifier(f.column)
        if f.op == "null":
            parts.append(sql.SQL("{} IS NULL").format(column))
        elif f.op == "notnull":
            parts.append(sql.SQL("{} IS NOT NULL").format(column))
        elif f.op == "contains":
            parts.append(sql.SQL("{}::text ILIKE %s").format(column))
            params.append(f"%{f.value}%")
        elif f.op in ("eq", "ne"):
            parts.append(sql.SQL("{}::text " + ("=" if f.op == "eq" else "<>") + " %s")
                         .format(column))
            params.append(f.value)
        else:
            parts.append(sql.SQL("{} " + _COMPARISONS[f.op] + " %s").format(column))
            params.append(f.value)
    if not parts:
        return sql.SQL(""), params
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(parts), params


def _order(table: Table, sort: str | None, direction: str) -> sql.Composable:
    """Sortowanie z rozstrzygnięciem remisów po kluczu głównym.

    Bez dokładki po kluczu strona 2 potrafi powtórzyć wiersze ze strony 1:
    przy równych wartościach kolumny sortującej PostgreSQL nie obiecuje
    stałej kolejności między zapytaniami.
    """
    key = table.primary_key or [table.columns[0].name]
    if sort and table.has_column(sort):
        way = sql.SQL("DESC" if direction == "desc" else "ASC")
        first = sql.SQL("{} {} NULLS LAST").format(sql.Identifier(sort), way)
        rest = [sql.Identifier(c) for c in key if c != sort]
        return sql.SQL(", ").join([first, *rest])
    return sql.SQL(", ").join(sql.Identifier(c) for c in key)


def list_rows(cur, sch: Schema, name: str, filters: list[Filter],
              sort: str | None = None, direction: str = "asc",
              page: int = 1, per_page: int = PER_PAGE) -> tuple[list[dict], int]:
    """Strona listy. Tylko allowlistowane kolumny; wartości zawsze jako parametry."""
    table = _table(sch, name)
    clause, params = _where(filters)
    order = _order(table, sort, direction)
    try:
        cur.execute(
            sql.SQL("SELECT count(*) AS n FROM {}{}").format(sql.Identifier(name), clause),
            params)
        total = cur.fetchone()["n"]
        cur.execute(
            sql.SQL("SELECT * FROM {}{} ORDER BY {} LIMIT %s OFFSET %s").format(
                sql.Identifier(name), clause, order),
            [*params, per_page, (page - 1) * per_page],
        )
        return cur.fetchall(), total
    except psycopg.DataError as e:
        # Np. `max_points > abc`: kolumna jest liczbą, wpisano tekst. Bez tej
        # gałęzi cała lista kończy się pięćsetką zamiast zdaniem przy formularzu.
        raise FilterError(
            f"Wartość filtru nie pasuje do typu kolumny ({e.diag.message_primary or e})."
        ) from e


def suggestions(cur, table: Table, sample: int = SUGGEST_LIMIT) -> dict[str, list[str]]:
    """Wartości do podpowiedzi przy filtrze — tylko kolumny o małej różnorodności.

    Po jednym zapytaniu na kolumnę kandydującą. Przy 1436 zadaniach i 3315
    warunkach to ułamek sekundy; przy maturze (K6) trzeba będzie to sprowadzić
    do listy wartości z więzów CHECK albo do cache'u.
    """
    out: dict[str, list[str]] = {}
    candidates = [c for c in table.columns
                  if c.type in ("text", "character varying", "boolean", "character")
                  or c.name.endswith("_status") or c.name in ("kind", "role", "action")]
    for column in candidates[:SUGGEST_COLUMNS]:
        cur.execute(
            sql.SQL("SELECT DISTINCT {}::text AS v FROM {} WHERE {} IS NOT NULL "
                    "ORDER BY 1 LIMIT %s").format(
                sql.Identifier(column.name), sql.Identifier(table.name),
                sql.Identifier(column.name)),
            (sample + 1,))
        values = [r["v"] for r in cur.fetchall()]
        if 0 < len(values) <= sample:
            out[column.name] = values
    return out


@dataclass
class ListView:
    """Stan listy — filtry, sortowanie, widoczne kolumny — i budowanie adresów.

    Linki liczy jeden obiekt, a nie szablon: „posortuj po tej kolumnie" ma
    zachować filtry, a „zdejmij filtr" — sortowanie. Sklejane w Jinji, rozjechałyby
    się przy pierwszej nowej opcji.
    """
    table: Table
    filters: list[Filter]
    sort: str | None = None
    direction: str = "asc"
    all_columns: bool = False
    page: int = 1
    per_page: int = PER_PAGE

    def url(self, *, drop: Filter | None = None, sort: str | None = None,
            page: int | None = None, all_columns: bool | None = None,
            per: int | None = None) -> str:
        parts: list[tuple[str, str]] = []
        for f in self.filters:
            if f is drop:
                continue
            parts.append((f.param, f.value if f.value is not None else ""))

        order, way = self.sort, self.direction
        if sort is not None:
            # Klik w tę samą kolumnę odwraca kierunek; w inną — zaczyna od rosnąco.
            way = "desc" if (order == sort and way == "asc") else "asc"
            order = sort
        if order:
            parts.append(("_sort", order))
            parts.append(("_dir", way))

        wide = self.all_columns if all_columns is None else all_columns
        if wide:
            parts.append(("_cols", "all"))

        target = self.page if page is None else page
        if target and target > 1:
            parts.append(("_page", str(target)))

        # `_per` jedzie w adresie tylko po to, żeby trasa zapisała je w ciasteczku.
        # Po przekierowaniu znika: rozmiar strony jest ustawieniem przeglądarki,
        # a nie częścią adresu, którym się dzieli.
        if per is not None:
            parts.append(("_per", str(per)))

        query = urlencode(parts)
        return f"/inspect/{self.table.name}" + (f"?{query}" if query else "")

    def arrow(self, column: str) -> str:
        if self.sort != column:
            return ""
        return " ▼" if self.direction == "desc" else " ▲"


def get_row(cur, sch: Schema, name: str, row_id: int) -> dict | None:
    table = _table(sch, name)
    key = table.single_key
    if key is None:
        return None
    cur.execute(sql.SQL("SELECT * FROM {} WHERE {} = %s").format(
        sql.Identifier(name), sql.Identifier(key)), (row_id,))
    return cur.fetchone()


def parents_of(sch: Schema, name: str, row: dict) -> list[dict]:
    table = _table(sch, name)
    out = []
    for column, (ref_table, ref_column) in table.parents.items():
        value = row.get(column)
        if value is None:
            continue
        out.append({"column": column, "table": ref_table, "ref_column": ref_column,
                    "value": value,
                    "url": f"/inspect/{ref_table}/{value}" if ref_column == "id"
                    else f"/inspect/{ref_table}?{ref_column}={value}"})
    return out


def children_of(cur, sch: Schema, name: str, row: dict) -> list[dict]:
    """Dzieci wiersza: liczba + kilka pierwszych, z linkiem do pełnej listy."""
    table = _table(sch, name)
    key = table.single_key
    if key is None:
        return []
    value = row[key]
    out = []
    for child_table, child_column in table.children:
        cur.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE {} = %s").format(
            sql.Identifier(child_table), sql.Identifier(child_column)), (value,))
        n = cur.fetchone()["n"]
        child = sch.tables[child_table]
        order = [sql.Identifier(c) for c in (child.primary_key or [child.columns[0].name])]
        cur.execute(
            sql.SQL("SELECT * FROM {} WHERE {} = %s ORDER BY {} LIMIT %s").format(
                sql.Identifier(child_table), sql.Identifier(child_column),
                sql.SQL(", ").join(order)),
            (value, CHILD_PREVIEW),
        )
        rows = cur.fetchall()
        out.append({
            "table": child_table, "column": child_column, "count": n,
            "rows": [summarize(sch, child_table, r) for r in rows],
            "url": f"/inspect/{child_table}?{child_column}={value}",
        })
    return out


def summarize(sch: Schema, name: str, row: dict) -> dict:
    """Wiersz w jednej linii: identyfikator + kolumny streszczające."""
    table = sch.tables[name]
    key = table.single_key
    columns = SUMMARY.get(name) or tuple(
        c.name for c in table.columns if c.name != key)[:4]
    parts = []
    for column in columns:
        if column in row and row[column] is not None:
            parts.append(f"{column}={format_value(row[column], short=True)}")
    return {
        "id": row.get(key) if key else None,
        "url": f"/inspect/{name}/{row[key]}" if key else None,
        "text": " · ".join(parts) or "(pusty)",
    }


# ------------------------------------------------------------- pochodzenie

@dataclass
class Provenance:
    """Gdzie w plikach leży to, co widać w wierszu."""
    document_id: int | None = None
    document_path: str | None = None
    document_pages: int | None = None
    document_kind: str | None = None
    file_exists: bool | None = None
    page: int | None = None
    # ramka w punktach PDF [x0, top, x1, bottom]; rysowana nad obrazem strony
    bbox: list[float] | None = None
    # rozmiar strony w punktach — potrzebny do viewBox nakładki SVG
    page_size: tuple[float, float] | None = None
    asset_id: int | None = None
    crop_exists: bool | None = None
    crop_path: str | None = None
    note: str | None = None
    # dokumenty powiązane inaczej niż „strona źródłowa" (np. wszystkie pliki formy)
    related: list[dict] = field(default_factory=list)


def _document(cur, document_id: int | None) -> dict | None:
    if document_id is None:
        return None
    cur.execute("SELECT id, path, pages, kind FROM document WHERE id = %s", (document_id,))
    return cur.fetchone()


def _key_page_of_task(cur, task_id: int) -> tuple[int | None, int | None]:
    cur.execute("SELECT marking_scheme_id, page FROM task WHERE id = %s", (task_id,))
    row = cur.fetchone()
    return (row["marking_scheme_id"], row["page"]) if row else (None, None)


def _task_of(cur, table: str, row: dict) -> int | None:
    """Zadanie, do którego wiersz należy — po łańcuchu kluczy obcych."""
    if "task_id" in row:
        return row["task_id"]
    if table == "task":
        return row["id"]
    if table == "criterion_condition":
        cur.execute("SELECT task_id FROM criterion WHERE id = %s", (row["criterion_id"],))
    elif table == "condition_expression":
        cur.execute(
            """SELECT c.task_id FROM criterion_condition cc
               JOIN criterion c ON c.id = cc.criterion_id WHERE cc.id = %s""",
            (row["condition_id"],))
    elif table == "model_answer" or table == "asset":
        cur.execute("SELECT task_id FROM task_version WHERE id = %s", (row["task_version_id"],))
    else:
        return None
    found = cur.fetchone()
    return found["task_id"] if found else None


def provenance(cur, table: str, row: dict) -> Provenance:
    """Reguły per tabela — spisane w docs/database-guide.html, sekcja „Chronologia"."""
    p = Provenance()

    if table == "document":
        _fill_document(p, row)
        p.page = 1
        p.note = "cały plik — podgląd otwiera się na pierwszej stronie"
    elif table == "task":
        _fill_document(p, _document(cur, row["marking_scheme_id"]))
        p.page = row.get("page")
        p.note = ("strona KLUCZA, z której wyjęto kryteria; zadanie nie ma ramki — "
                  "cała strona")
    elif table == "task_version":
        if row.get("paper_id"):
            _fill_document(p, _document(cur, row["paper_id"]))
            p.page = row.get("page")
            p.note = "strona ZESZYTU ZADAŃ z treścią; bbox treści nikt dziś nie zapisuje"
        else:
            doc_id, page = _key_page_of_task(cur, row["task_id"])
            _fill_document(p, _document(cur, doc_id))
            p.page = page
            p.note = "wersja bez zeszytu w bazie — pokazana strona klucza zadania"
    elif table == "asset":
        _fill_asset(cur, p, row)
    elif table == "rule":
        _fill_document(p, _document(cur, row["marking_scheme_id"]))
        p.note = ("reguła całego arkusza — nie ma numeru strony; sekcji „Uwagi ogólne”"
                  " szuka się przewijając klucz")
    elif table == "exam_form":
        cur.execute(
            """SELECT d.id, d.path, d.kind, fd.role FROM exam_form_document fd
               JOIN document d ON d.id = fd.document_id WHERE fd.exam_form_id = %s
               ORDER BY fd.role""",
            (row["id"],))
        p.related = [dict(r) for r in cur.fetchall()]
        p.note = "forma nie jest plikiem — plik jest nośnikiem; niżej wszystkie jej dokumenty"
    elif table in ("requirement", "requirement_regime"):
        p.note = ("wymaganie nie ma własnej strony — cytują je tabele przy zadaniach; "
                  "zadania niżej, w dzieciach")
    elif table in ("schema_migrations", "answer_example"):
        p.note = "bez źródła w plikach CKE"
    else:
        task_id = _task_of(cur, table, row)
        if task_id is not None:
            doc_id, page = _key_page_of_task(cur, task_id)
            _fill_document(p, _document(cur, doc_id))
            p.page = page
            p.note = (f"dziedziczone po zadaniu #{task_id}: strona klucza, "
                      "bez ramki wokół tego konkretnego wiersza")
    return p


def _fill_document(p: Provenance, doc: dict | None) -> None:
    if doc is None:
        return
    p.document_id = doc["id"]
    p.document_path = doc["path"]
    p.document_pages = doc.get("pages")
    p.document_kind = doc.get("kind")
    try:
        p.file_exists = pages.source_pdf(doc["path"]).exists()
    except pages.PageUnavailable:
        p.file_exists = False


def _fill_asset(cur, p: Provenance, row: dict) -> None:
    cur.execute(
        """SELECT DISTINCT ON (a.id) d.id, d.path, d.pages, d.kind
           FROM asset a
           JOIN task_version tv ON tv.id = a.task_version_id
           JOIN exam_form f ON f.id = tv.exam_form_id
           LEFT JOIN exam_form_document fd ON fd.exam_form_id = f.id AND fd.role = 'paper'
           LEFT JOIN document d ON d.id = fd.document_id
           WHERE a.id = %s ORDER BY a.id, f.variant, f.version""",
        (row["id"],))
    doc = cur.fetchone()
    if doc and doc["id"] is not None:
        _fill_document(p, doc)
    p.page = row.get("page")
    p.bbox = [float(v) for v in row["bbox"]] if row.get("bbox") else None
    p.asset_id = row["id"]
    try:
        target = crop_pdf.target_path(row["path"])
        p.crop_path = str(target)
        p.crop_exists = target.exists()
    except crop_pdf.CropError as e:
        p.crop_exists = False
        p.note = f"ścieżka bloba odrzucona: {e}"
    if p.document_path and p.file_exists and p.page:
        p.page_size = page_size(p.document_path, p.page)
    if p.note is None:
        p.note = ("ramka w punktach PDF nad stroną zeszytu; obok wycinek z bloba — "
                  "gdy się nie zgadzają, ramkę zmieniono po ostatnim cięciu")


def viewed_page(raw: str | None, source: Provenance) -> int:
    """Strona pokazywana w podglądzie: z adresu, inaczej ta z rekordu, inaczej pierwsza.

    Numer jedzie pod `_pdfpage`, a nie `page`: `page` jest KOLUMNĄ w trzech tabelach
    i raz już zabrało nazwę parametrowi widoku. Wartość spoza dokumentu przycina się
    do jego zakresu, zamiast pokazywać pustą ramkę po literówce w adresie.
    """
    page = int(raw) if raw and raw.isdigit() and int(raw) > 0 else (source.page or 1)
    if source.document_pages:
        page = min(page, source.document_pages)
    return max(page, 1)


def page_size(relative_path: str, page: int) -> tuple[float, float] | None:
    """Rozmiar strony w punktach, z PNG w cache'u — bez drugiego otwierania PDF-u."""
    try:
        from PIL import Image
        with Image.open(pages.render(relative_path, page)) as image:
            return (image.size[0] / pages.SCALE, image.size[1] / pages.SCALE)
    except (pages.PageUnavailable, OSError):
        return None


# ------------------------------------------------------------ zdrowie danych

@dataclass(frozen=True)
class Check:
    key: str
    title: str
    why: str
    table: str
    query: str
    severity: str = "problem"  # 'problem' | 'info'
    # filtr w Pythonie dla warunków, których SQL nie zna (istnienie pliku na dysku)
    keep: Callable[[dict], bool] | None = None


def _pdf_missing(row: dict) -> bool:
    try:
        return not pages.source_pdf(row["path"]).exists()
    except pages.PageUnavailable:
        return True


def _crop_missing(row: dict) -> bool:
    try:
        return not crop_pdf.target_path(row["path"]).exists()
    except crop_pdf.CropError:
        return True


CHECKS: tuple[Check, ...] = (
    Check("open_without_criteria", "Zadania otwarte bez kryteriów",
          "Otwarte zadanie bez progów nie da się ocenić — parser zgubił sekcję albo "
          "zadanie jest źle sklasyfikowane.",
          "task",
          """SELECT t.id, t.number, t.max_points, t.kind, t.review_status
             FROM task t WHERE t.kind <> 'closed'
               AND NOT EXISTS (SELECT 1 FROM criterion c WHERE c.task_id = t.id)
             ORDER BY t.id"""),
    Check("closed_without_answer", "Zadania zamknięte bez odpowiedzi wzorcowej",
          "EvaluateClosed nie ma z czym porównać. Zwykle: wersja bez litery i klucz "
          "z dwiema kolumnami odpowiedzi (naprawione 4.09), albo brak tabeli w kluczu.",
          "task",
          """SELECT t.id, t.number, t.review_status FROM task t
             WHERE t.kind = 'closed'
               AND NOT EXISTS (SELECT 1 FROM task_version tv
                               JOIN model_answer m ON m.task_version_id = tv.id
                               WHERE tv.task_id = t.id)
             ORDER BY t.id"""),
    Check("task_without_requirement", "Zadania bez wymagania podstawy",
          "Mapa braków tego zadania nie zobaczy.",
          "task",
          """SELECT t.id, t.number, t.review_status FROM task t
             WHERE NOT EXISTS (SELECT 1 FROM task_requirement tr WHERE tr.task_id = t.id)
             ORDER BY t.id"""),
    Check("asset_full_page", "Zasoby z ramką „cała strona”",
          "bbox zaczyna się w rogu (0, 0) — detektor nie znalazł regionu; "
          "robota dla task frame albo ręcznej ramki.",
          "asset",
          """SELECT a.id, a.kind, a.page, a.path FROM asset a
             WHERE a.bbox[1] = 0 AND a.bbox[2] = 0 ORDER BY a.id"""),
    Check("asset_without_crop", "Zasoby bez pliku wycinka w blobie",
          "Wiersz jest, PNG nie ma. Dziś to ten sam zbiór co „cała strona”: task crops "
          "takich ramek nie tnie. Wiersz spoza tamtej listy to prawdziwa dziura w blobie.",
          "asset",
          "SELECT a.id, a.kind, a.page, a.path FROM asset a ORDER BY a.id",
          keep=_crop_missing),
    Check("expression_failed", "Zapisy równoważne odrzucone przez konwerter MathJSON",
          "A3 traktuje je jak warunek tekstowy. Powód w mathjson_error; ten sam powód "
          "w wielu wierszach = błąd systematyczny do naprawy w normalize.py.",
          "condition_expression",
          """SELECT e.id, e.expression, e.mathjson_error FROM condition_expression e
             WHERE e.mathjson_status = 'failed' ORDER BY e.mathjson_error, e.id"""),
    Check("document_missing_file", "Dokumenty, których pliku nie ma w mirrorze",
          "Baza wskazuje ścieżkę, dysk jej nie ma — MIRROR_ROOT źle ustawiony "
          "albo mirror niepełny. To NIE jest to samo, co NULL.",
          "document",
          "SELECT d.id, d.kind, d.code, d.session, d.path FROM document d ORDER BY d.id",
          keep=_pdf_missing),
    Check("version_without_content", "Wersje zadań bez treści",
          "Zeszytu nie ma w mirrorze albo klucz wczytano bez --with-papers. "
          "Golden set rekonstruuje wtedy treść z klucza.",
          "task_version",
          """SELECT tv.id, tv.task_id, tv.exam_form_id, tv.page FROM task_version tv
             WHERE tv.content IS NULL ORDER BY tv.id""",
          severity="info"),
    Check("event_orphans", "Wpisy dziennika bez zadania",
          "Sieroty po przeładowaniu klucza z --overwrite-reviewed. Celowo zostają "
          "(pomiar S8), ale ich liczba mówi, ile razy korpus przeładowano po korekcie.",
          "correction_event",
          """SELECT e.id, e.action, e.actor, e.finished_at FROM correction_event e
             WHERE e.task_id IS NULL ORDER BY e.id""",
          severity="info"),
    Check("requirement_unused", "Wymagania, których nie sprawdza żadne zadanie",
          "Naturalne przy jednym wariancie w korpusie; mapa braków w A4 potrzebuje "
          "pokrycia. Liczone po całej tabeli task, nie po korpusie.",
          "requirement",
          """SELECT r.id, r.kind, r.stage, r.path FROM requirement r
             WHERE r.kind = 'specific'
               AND NOT EXISTS (SELECT 1 FROM task_requirement tr WHERE tr.requirement_id = r.id)
             ORDER BY r.path""",
          severity="info"),
    Check("model_notes", "Uwagi modelu przy rozstrzygnięciu — kandydaci do próbki ludzkiej",
          "verify zatwierdził (match), ale zostawił zastrzeżenie w notes — najczęściej "
          "rozjazd wymagania podstawy. To lista do ręcznego przejrzenia.",
          "correction_event",
          """SELECT e.id, e.task_id, e.action, e.fields_changed FROM correction_event e
             WHERE e.actor = 'model' AND (e.action = 'unsure' OR e.fields_changed ? 'notes')
             ORDER BY e.id DESC""",
          severity="info"),
)

CHECK_BY_KEY = {c.key: c for c in CHECKS}


def run_check(cur, check: Check, limit: int | None = None) -> list[dict]:
    cur.execute(check.query)
    rows = cur.fetchall()
    if check.keep is not None:
        rows = [r for r in rows if check.keep(r)]
    return rows[:limit] if limit else rows


def health(cur) -> list[dict]:
    """Wszystkie kontrole naraz — same liczby; listy dopiero na żądanie."""
    out = []
    for check in CHECKS:
        rows = run_check(cur, check)
        out.append({"check": check, "count": len(rows)})
    return out


# Kolumny, które schemat obiecuje, a żaden przebieg nie wypełnia — licznik dla
# przypomnienia. Zapytanie mówi, ile wierszy ma wartość „nietkniętą".
EMPTY_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("document", "sha256", "sha256 IS NULL"),
    ("requirement", "parent_id", "parent_id IS NULL"),
    ("task_version", "bbox", "bbox IS NULL"),
    ("task_version", "content_status", "content_status = 'auto'"),
    ("requirement_regime", "session_to", "session_to IS NULL"),
)


def empty_columns(cur) -> list[dict]:
    out = []
    for table, column, condition in EMPTY_COLUMNS:
        # `condition` jest STAŁĄ z tego pliku, nie z żądania — stąd bez parametrów.
        cur.execute(sql.SQL("SELECT count(*) FILTER (WHERE {}) AS untouched, count(*) AS total "
                            "FROM {}").format(sql.SQL(condition), sql.Identifier(table)))
        row = cur.fetchone()
        out.append({"table": table, "column": column, "untouched": row["untouched"],
                    "total": row["total"]})
    return out


# ------------------------------------------------------------------- format

def format_value(value, short: bool = False) -> str:
    """Wartość do wyświetlenia. Krótka forma ucina długie teksty w listach."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)) and not _is_bbox(value):
        text = json.dumps(value, ensure_ascii=False, indent=None if short else 2)
    elif isinstance(value, list):
        text = "[" + ", ".join(f"{float(v):g}" for v in value) + "]"
    elif isinstance(value, (datetime, date)):
        text = value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    elif isinstance(value, Decimal):
        text = f"{value:g}"
    else:
        text = str(value)
    if short and len(text) > 80:
        return text[:77] + "…"
    return text


def _is_bbox(value) -> bool:
    return (isinstance(value, list) and len(value) == 4
            and all(isinstance(v, (int, float, Decimal)) for v in value))


def is_json(value) -> bool:
    return isinstance(value, (dict, list)) and not _is_bbox(value)
