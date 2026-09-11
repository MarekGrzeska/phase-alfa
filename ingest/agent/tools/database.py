"""Baza: schemat z pochodzeniem kolumn, dowolny SELECT tylko do odczytu, inspektor.

Czytanie bez ograniczeń, ale w transakcji `READ ONLY` z limitem czasu i wierszy.
Zapis surowym SQL-em (`db_execute`) tylko po zgodzie człowieka — z podglądem
liczby wierszy z wycofanej próby. Nazwy tabel i kolumn idą przez allowlistę inspektora.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from psycopg.rows import dict_row

from agent import audit, confirm, limits
from correction import db, inspector
from schema import migrate

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

# Zapytanie, które trwa dłużej, blokuje ekran korekty na tej samej bazie —
# a agent i tak nie przeczyta miliona wierszy. Limit stoi też na roli (migracja
# 0011), bo `SET LOCAL` w transakcji dawał się zdjąć treścią zapytania.
STATEMENT_TIMEOUT = "15s"

# Rola z migracji 0011: tylko SELECT, bez uprawnień superusera. Hasło jest
# wartością konfiguracji, nie sekretem — tak samo jak `klucz_dev` w docker-compose;
# baza słucha na 127.0.0.1. Wdrożenie poza localhost nadpisuje `AGENT_DATABASE_URL`.
AGENT_ROLE = "klucz_agent"
AGENT_PASSWORD_ENV = "AGENT_DB_PASSWORD"  # noqa: S105 - nazwa zmiennej, nie hasło
AGENT_PASSWORD_DEFAULT = "klucz_agent_dev"  # noqa: S105 - hasło bazy deweloperskiej

MISSING_ROLE = (
    f"Brak roli `{AGENT_ROLE}` w bazie albo złe hasło — odczyt agenta chodzi na roli "
    "bez uprawnień superusera (migracja 0011). Uruchom `task migrate`. Do czasu "
    "migracji `db_query` jest niedostępne; czytać można narzędziami `inspect_*`, "
    "`task_get` i `db_health`."
)


def agent_url() -> str:
    """Adres bazy dla odczytu agenta — ta sama baza, inna rola.

    Osobne połączenie, a nie `SET LOCAL ROLE` na połączeniu `klucz`: `klucz` jest
    superuserem, więc `RESET ROLE` w treści zapytania wróciłby do pełnych uprawnień.
    """
    given = os.environ.get("AGENT_DATABASE_URL")
    if given:
        return given
    password = os.environ.get(AGENT_PASSWORD_ENV) or AGENT_PASSWORD_DEFAULT
    parts = urlsplit(migrate.polaczenie())
    host = parts.hostname or "localhost"
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit(parts._replace(
        netloc=f"{quote(AGENT_ROLE)}:{quote(password)}@{host}{port}"))


def reader() -> psycopg.Connection:
    """Połączenie tylko do odczytu. Brak roli to GŁOŚNA porażka, nie cichy powrót.

    Gdyby przy braku roli kod wracał do połączenia `klucz`, dziura z przeglądu
    (komentarz 1) otwierałaby się sama na każdej bazie bez migracji 0011.
    """
    try:
        return psycopg.connect(agent_url(), row_factory=dict_row)
    except psycopg.OperationalError as exc:
        raise ValueError(f"{MISSING_ROLE}\n({exc})") from exc


def table_summary(sch: inspector.Schema, table: inspector.Table) -> dict:
    return {
        "name": table.name,
        "note": inspector.TABLE_NOTES.get(table.name, ""),
        "primary_key": list(table.primary_key),
        "columns": [
            {"name": c.name, "type": c.type, "nullable": c.nullable, "default": c.default,
             "written_by": inspector.source_of(table.name, c.name),
             "references": (f"{table.parents[c.name][0]}.{table.parents[c.name][1]}"
                            if c.name in table.parents else None),
             "allowed_values": sch.enums.get(table.name, {}).get(c.name)}
            for c in table.columns
        ],
        "children": [f"{child}.{column}" for child, column in table.children],
    }


def run_read_only(con: psycopg.Connection, sql: str, limit: int) -> dict:
    """SELECT w transakcji tylko do odczytu; `limit + 1` wierszy, żeby wiedzieć o cięciu.

    Kursor jest NAZWANY, czyli serwerowy: bez tego psycopg pobiera cały wynik do
    pamięci procesu już przy `execute`, więc `SELECT * FROM criterion` ściągało
    3315 wierszy, żeby oddać dwieście (przegląd 11.09.2026, komentarz 8). Ekran
    korekty siedzi w tym samym procesie i dzieli z agentem pamięć.
    """
    con.read_only = True
    with con.transaction():
        with con.cursor() as plain:
            # Stała z tego pliku, nie z żądania — stąd bez parametru. Drugi limit,
            # obok ustawienia roli z migracji 0011: to jest pas, tamto szelki.
            # `SET LOCAL` obowiązuje do końca TEJ transakcji, więc oba kursory
            # muszą siedzieć w jednej.
            plain.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
        with con.cursor(name="agent_query") as cur:
            cur.execute(sql)
            if cur.description is None:
                return {"columns": [], "rows": [], "row_count": 0, "truncated": False,
                        "note": "polecenie nie zwróciło wierszy"}
            columns = [d.name for d in cur.description]
            fetched = cur.fetchmany(limit + 1)
    rows = [[limits.clip_cell(row[c]) for c in columns] for row in fetched[:limit]]
    truncated = len(fetched) > limit
    out = {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}
    if truncated:
        out["hint"] = f"Wynik ucięty do {limit} wierszy. {limits.NARROW_HINT}"
    return out


# Polecenia, które wolno oddać kursorowi serwerowemu. Cokolwiek innego kończy się
# błędem składni przy `DECLARE … CURSOR FOR`, a model ma dostać z tego wniosek,
# nie surowy komunikat Postgresa.
READ_STARTS = ("select", "with", "values", "explain", "table", "show")


def friendly_sql_error(exc: psycopg.Error, sql: str = "", *, read_only: bool = False) -> str:
    if isinstance(exc, psycopg.errors.ReadOnlySqlTransaction):
        return ("To zapytanie zmienia dane, a `db_query` jest tylko do odczytu. "
                "Zapis do korpusu: narzędzia `task_*`; surowy SQL: `db_execute` "
                "(z potwierdzeniem człowieka).")
    if read_only and isinstance(exc, psycopg.errors.SyntaxError):
        first = sql.strip().split(None, 1)[0].lower() if sql.strip() else ""
        if first and not first.startswith(READ_STARTS):
            return (f"`db_query` wykonuje JEDNO polecenie odczytu (SELECT, WITH, VALUES, "
                    f"EXPLAIN), a to zaczyna się od `{first.upper()}`. Zapis do korpusu: "
                    f"narzędzia `task_*`; surowy SQL: `db_execute` (za zgodą człowieka). "
                    f"Dwóch poleceń rozdzielonych średnikiem też nie przyjmuje.")
    if isinstance(exc, psycopg.errors.InsufficientPrivilege):
        # Odczyt agenta chodzi na roli bez uprawnień superusera (migracja 0011):
        # `COPY … TO PROGRAM`, `pg_read_file` i spółka odmawiają właśnie tutaj.
        return ("Baza odmówiła: rola odczytu agenta ma prawo wyłącznie do SELECT-a "
                "na tabelach korpusu. Konstrukcje sięgające poza dane (COPY, funkcje "
                "plikowe, tabele tymczasowe) są poza jej zasięgiem — i tak ma być.")
    if isinstance(exc, psycopg.errors.QueryCanceled):
        return f"Zapytanie przekroczyło limit {STATEMENT_TIMEOUT}. {limits.NARROW_HINT}"
    return exc.diag.message_primary or str(exc)


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def db_schema(table: str | None = None) -> dict:
        """Schemat bazy korpusu: tabele, kolumny, typy, klucze obce, wartości CHECK
        i KTO pisze każdą kolumnę (parser, ładowarka, ekran, verify, nikt).

        Bez `table` — spis wszystkich tabel z notatką i liczbą kolumn; z `table` —
        pełny opis jednej. Widoki (`corpus_task`, `twins`, …) w polu `views`.
        """
        with db.connect() as con, con.cursor() as cur:
            sch = inspector.schema(cur)
            if table is not None:
                if table not in sch:
                    raise ValueError(f"nie ma takiej tabeli: {table}; "
                                     f"znane: {', '.join(sch.tables)}")
                return table_summary(sch, sch.tables[table])
            counts = inspector.counts(cur, sch)
            return {
                "tables": [{"name": name, "rows": counts[name], "columns": len(t.columns),
                            "note": inspector.TABLE_NOTES.get(name, "")}
                           for name, t in sch.tables.items()],
                "views": list(sch.views),
                "written_by_legend": ("parser = z PDF-u klucza; ładowarka = z relacji przy "
                                      "zapisie; ekran = człowiek w ekranie korekty; "
                                      "verify/prefill/describe/frame = przebiegi LLM; "
                                      "nikt = kolumna obiecana przez schemat, dziś pusta"),
            }

    @mcp.tool(annotations=READ_ONLY)
    def db_query(sql: str, limit: int = limits.MAX_ROWS) -> dict:
        """Dowolne zapytanie SQL tylko do odczytu (SELECT, WITH, EXPLAIN) na bazie korpusu.

        Chodzi na roli, która ma WYŁĄCZNIE prawo SELECT-a (bez uprawnień superusera),
        w transakcji READ ONLY, z limitem czasu 15 s i najwyżej `limit` wierszami
        (domyślnie 200) — wynik ucięty ma `truncated: true`. Jedno polecenie na raz.
        Korpus to widok `corpus_task`; tabela `task` zawiera też rekordy
        nierozstrzygnięte. Schemat: `db_schema`.
        """
        limit = max(1, min(int(limit), limits.MAX_ROWS))
        try:
            with reader() as con:
                return run_read_only(con, sql, limit)
        except psycopg.Error as exc:
            raise ValueError(friendly_sql_error(exc, sql, read_only=True)) from exc

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                          idempotentHint=False, openWorldHint=False),
              meta={"confirm": True})
    def db_execute(sql: str, confirmation: int | None = None) -> dict:
        """Surowy SQL zmieniający dane (INSERT/UPDATE/DELETE/DDL) — WYŁĄCZNIE za zgodą
        człowieka. Bez `confirmation` wykonuje zapytanie na próbę w wycofanej
        transakcji, zapisuje prośbę o zgodę z treścią i liczbą dotkniętych wierszy
        i zwraca ją; nic nie zmienia. Z `confirmation=<id>` po kliknięciu „Wykonaj"
        wykonuje i zatwierdza. Do zmian w korpusie używaj narzędzi `task_*`, nie tego.
        """
        arguments = {"sql": sql}
        try:
            with db.connect() as con:
                if confirmation is None:
                    with con.cursor() as cur:
                        cur.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                        cur.execute(sql)
                        affected = cur.rowcount
                    con.rollback()
                    with con.transaction(), con.cursor() as cur:
                        return confirm.request(
                            cur, "db_execute", arguments, "Surowy zapis SQL",
                            f"{sql.strip()}\n-- dotknie wierszy (próba): {affected}")
                with con.transaction(), con.cursor() as cur:
                    confirm.consume(cur, int(confirmation), "db_execute", arguments)
                    cur.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                    cur.execute(sql)
                    affected = cur.rowcount
                    audit.record(cur, "db_execute", arguments, {"affected_rows": affected},
                                 confirmation_id=int(confirmation))
        except psycopg.Error as exc:
            raise ValueError(friendly_sql_error(exc)) from exc
        return {"affected_rows": affected, "confirmation": int(confirmation)}

    @mcp.tool(annotations=READ_ONLY)
    def inspect_list(table: str, filters: dict[str, str] | None = None,
                     sort: str | None = None, direction: str = "asc",
                     page: int = 1, per_page: int = 50) -> dict:
        """Lista wierszy tabeli z filtrami inspektora — te same, które widzi człowiek.

        `filters`: {"kolumna": wartość} to równość, {"kolumna__op": wartość} to operator
        (eq, ne, contains, gt, gte, lt, lte, null, notnull). Filtr po nieznanej kolumnie
        jest POMIJANY i wymieniony w `rejected`. Wynik ma `url` — ten sam widok
        w inspektorze, do `ui_navigate` albo do wklejenia.
        """
        per_page = max(1, min(int(per_page), limits.MAX_ROWS))
        with db.connect() as con, con.cursor() as cur:
            sch = inspector.schema(cur)
            if table not in sch:
                raise ValueError(f"nie ma takiej tabeli: {table}")
            meta = sch.tables[table]
            parsed, rejected, _ = inspector.parse_filters(
                meta, [(k, "" if v is None else str(v)) for k, v in (filters or {}).items()])
            view = inspector.ListView(
                table=meta, filters=parsed,
                sort=sort if sort and meta.has_column(sort) else None,
                direction="desc" if direction == "desc" else "asc",
                page=max(1, int(page)), per_page=per_page)
            try:
                rows, total = inspector.list_rows(cur, sch, table, parsed, view.sort,
                                                  view.direction, view.page, per_page)
            except inspector.FilterError as e:
                raise ValueError(str(e)) from e
            return {
                "table": table, "total": total, "page": view.page, "per_page": per_page,
                "rows": [{k: limits.clip_cell(v) for k, v in row.items()} for row in rows],
                "rejected": rejected,
                "url": view.url(),
            }

    @mcp.tool(annotations=READ_ONLY)
    def inspect_record(table: str, id: int) -> dict:
        """Jeden wiersz z pochodzeniem: rodzice, dzieci, plik PDF i strona, z której
        pochodzi, wycinek w blobie i czy pliki są na dysku."""
        with db.connect() as con, con.cursor() as cur:
            sch = inspector.schema(cur)
            if table not in sch:
                raise ValueError(f"nie ma takiej tabeli: {table}")
            if sch.tables[table].single_key is None:
                raise ValueError(f"tabela {table} ma klucz złożony — użyj inspect_list")
            row = inspector.get_row(cur, sch, table, id)
            if row is None:
                raise ValueError(f"nie ma wiersza {table} #{id}")
            return {
                "table": table, "id": id,
                "row": {k: limits.clip_cell(v) for k, v in row.items()},
                "notes": inspector.row_provenance(table, row),
                "parents": inspector.parents_of(sch, table, row),
                "children": limits.jsonable(inspector.children_of(cur, sch, table, row)),
                "source": limits.jsonable(asdict(inspector.provenance(cur, table, row))),
                "url": f"/inspect/{table}/{id}",
            }

    @mcp.tool(annotations=READ_ONLY)
    def db_health(key: str | None = None, limit: int = 50) -> dict:
        """Kontrole zdrowia danych. Bez `key` — wszystkie z liczbami trafień;
        z `key` — wiersze jednej kontroli (z `url` do listy w inspektorze)."""
        with db.connect() as con, con.cursor() as cur:
            if key is None:
                return {"checks": [
                    {"key": item["check"].key, "title": item["check"].title,
                     "why": item["check"].why, "severity": item["check"].severity,
                     "table": item["check"].table, "count": item["count"],
                     "url": f"/inspect/health/{item['check'].key}"}
                    for item in inspector.health(cur)]}
            check = inspector.CHECK_BY_KEY.get(key)
            if check is None:
                raise ValueError(f"nie ma takiej kontroli: {key}; znane: "
                                 f"{', '.join(inspector.CHECK_BY_KEY)}")
            rows = inspector.run_check(cur, check)
            out = limits.row_dicts(rows, max(1, min(int(limit), limits.MAX_ROWS)))
            out.update({"key": key, "title": check.title, "why": check.why,
                        "severity": check.severity, "url": f"/inspect/health/{key}"})
            return out

    @mcp.tool(annotations=READ_ONLY)
    def db_migrations() -> dict:
        """Stan migracji schematu: które weszły, których brakuje, czy sumy SHA się zgadzają."""
        with db.connect() as con, con.cursor() as cur:
            cur.execute(migrate.TABELA)
            applied = {r["version"]: r["sha256"] for r in
                       (cur.execute("SELECT version, sha256 FROM schema_migrations")
                        .fetchall())}
        files = migrate.migracje(migrate.KATALOG)
        return {"migrations": [
            {"version": version, "applied": version in applied,
             "changed_after_apply": version in applied and applied[version] != sha}
            for version, _, sha in files],
            "applied": sum(1 for v, _, _ in files if v in applied), "total": len(files)}
