"""Baza: schemat z pochodzeniem kolumn, dowolny SELECT tylko do odczytu, inspektor.

Czytanie bez ograniczeń, ale w transakcji `READ ONLY` z limitem czasu i wierszy.
Zapis surowym SQL-em (`db_execute`) wchodzi w M2 razem z potwierdzeniem —
tu go celowo nie ma. Nazwy tabel i kolumn idą przez allowlistę inspektora.
"""

from __future__ import annotations

from dataclasses import asdict

import psycopg
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from agent import limits
from correction import db, inspector
from schema import migrate

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

# Zapytanie, które trwa dłużej, blokuje ekran korekty na tej samej bazie —
# a agent i tak nie przeczyta miliona wierszy.
STATEMENT_TIMEOUT = "15s"


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
    """SELECT w transakcji tylko do odczytu; `limit + 1` wierszy, żeby wiedzieć o cięciu."""
    con.read_only = True
    with con.transaction(), con.cursor() as cur:
        # Stała z tego pliku, nie z żądania — stąd bez parametru.
        cur.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
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


def friendly_sql_error(exc: psycopg.Error) -> str:
    if isinstance(exc, psycopg.errors.ReadOnlySqlTransaction):
        return ("To zapytanie zmienia dane, a `db_query` jest tylko do odczytu. "
                "Zapis do korpusu: narzędzia `task_*`; surowy SQL: `db_execute` "
                "(z potwierdzeniem człowieka).")
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

        Transakcja READ ONLY, limit czasu 15 s, najwyżej `limit` wierszy (domyślnie 200)
        — wynik ucięty ma `truncated: true`. Korpus to widok `corpus_task`; tabela `task`
        zawiera też rekordy nierozstrzygnięte. Schemat: `db_schema`.
        """
        limit = max(1, min(int(limit), limits.MAX_ROWS))
        try:
            with db.connect() as con:
                return run_read_only(con, sql, limit)
        except psycopg.Error as exc:
            raise ValueError(friendly_sql_error(exc)) from exc

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
