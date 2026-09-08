"""JSON inspektora — te same dane, które dostawał szablon, bez HTML-a wokół nich.

Formatowanie wartości ZOSTAJE po stronie Pythona (`inspector.format_value`).
Front dostaje gotowy tekst plus tyle struktury, ile trzeba na odnośniki —
inaczej reguła „jak pokazać `bbox`, a jak `jsonb`" żyłaby w dwóch miejscach
i rozjechała się przy pierwszej zmianie.

Adresy też liczy `ListView`, a nie front: „posortuj po tej kolumnie" ma
zachować filtry, a „zdejmij filtr" — sortowanie.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from correction import db, inspector

router = APIRouter(prefix="/api/inspect")

# Kolumny, których wartość jest stanem, a nie treścią — front rysuje je znacznikiem.
STATUS_COLUMNS = frozenset({
    "review_status", "description_status", "mathjson_status", "ingest_status",
    "content_status",
})


def _known_table(sch: inspector.Schema, name: str) -> inspector.Table:
    # Nazwa tabeli z adresu przechodzi przez allowlistę ze schematu, a nieznana
    # kończy się 404 — nie ma drogi z URL-a do tekstu SQL-a.
    if name not in sch:
        raise HTTPException(404, f"nie ma takiej tabeli: {name}")
    return sch.tables[name]


def _cell(value) -> dict:
    """Wartość do pokazania: krótka w tabeli, pełna w dymku."""
    return {"text": inspector.format_value(value, short=True),
            "full": inspector.format_value(value)}


def _columns_of(table: inspector.Table) -> list[dict]:
    return [
        {
            "name": column.name,
            "type": column.type,
            "nullable": column.nullable,
            "default": column.default,
            "source": inspector.source_of(table.name, column.name),
            "parent": table.parents[column.name][0] if column.name in table.parents else None,
        }
        for column in table.columns
    ]


@router.get("")
def index() -> dict:
    """Spis tabel, zdrowie danych i kolumny, których nikt nie wypełnia."""
    with db.connect() as con, con.cursor() as cur:
        sch = inspector.schema(cur)
        counts = inspector.counts(cur, sch)
        return {
            "tables": [{"name": name, "count": counts[name],
                        "note": inspector.TABLE_NOTES.get(name, "")}
                       for name in sch.tables],
            "views": list(sch.views),
            "health": [{"key": item["check"].key, "title": item["check"].title,
                        "why": item["check"].why, "severity": item["check"].severity,
                        "count": item["count"]}
                       for item in inspector.health(cur)],
            "empty_columns": inspector.empty_columns(cur),
        }


@router.get("/health/{key}")
def health(key: str) -> dict:
    check = inspector.CHECK_BY_KEY.get(key)
    if check is None:
        raise HTTPException(404, f"nie ma takiej kontroli: {key}")
    with db.connect() as con, con.cursor() as cur:
        sch = inspector.schema(cur)
        rows = inspector.run_check(cur, check)
        table = sch.tables.get(check.table)
        columns = list(rows[0].keys()) if rows else []
        return {
            "check": {"key": check.key, "title": check.title, "why": check.why,
                      "severity": check.severity, "table": check.table},
            "columns": columns,
            "rows": [
                [{**_cell(row[column]),
                  # Identyfikator prowadzi do wiersza, klucz obcy — do rodzica.
                  # Bez tego kontrola mówi „coś jest nie tak" i zostawia szukanie.
                  "link": _health_link(check, table, column, row[column])}
                 for column in columns]
                for row in rows
            ],
        }


def _health_link(check, table: inspector.Table | None, column: str, value) -> str | None:
    if table is None or value is None:
        return None
    if column == "id" and table.single_key:
        return f"/inspect/{check.table}/{value}"
    if column.endswith("_id") and column in table.parents:
        return f"/inspect/{table.parents[column][0]}/{value}"
    return None


@router.get("/{table}")
def rows(request: Request, table: str) -> dict:
    # Stan widoku czytany z `query_params`, a NIE przez parametry funkcji: FastAPI
    # odrzuciłby `_page=` pustym stringiem z 422, a wiersz filtrów wysyła puste pola
    # przy każdej zmianie. Tu pusta wartość ma znaczyć „domyślna".
    params = request.query_params
    sort = params.get("_sort") or ""
    raw_page = params.get("_page") or ""
    per_page = inspector.per_page_or_default(params.get("_per"))

    with db.connect() as con, con.cursor() as cur:
        sch = inspector.schema(cur)
        meta = _known_table(sch, table)
        filters, rejected, _ = inspector.parse_filters(meta, params.multi_items())

        view = inspector.ListView(
            table=meta, filters=filters,
            sort=sort if meta.has_column(sort) else None,
            direction="desc" if params.get("_dir") == "desc" else "asc",
            all_columns=params.get("_cols") == "all",
            page=int(raw_page) if raw_page.isdigit() and int(raw_page) > 0 else 1,
            per_page=per_page,
        )

        errors = []
        if rejected:
            errors.append("Filtr po nieznanej kolumnie albo operatorze, pominięty: "
                          + ", ".join(rejected))
        try:
            found, total = inspector.list_rows(cur, sch, table, filters, view.sort,
                                               view.direction, view.page, per_page)
        except inspector.FilterError as e:
            # Odrzucone zapytanie zrywa transakcję: bez wycofania każde następne
            # (choćby podpowiedzi do formularza) wraca z „current transaction is
            # aborted", czyli literówka w filtrze kończy się pięćsetką mimo gałęzi obok.
            con.rollback()
            found, total = [], 0
            errors.append(str(e))

        hints = inspector.suggestions(cur, meta)
        active = {f.column: f for f in filters}
        described = inspector.column_filters(meta, sch.enums.get(table, {}), hints,
                                             inspector.table_size(cur, table))
        key = meta.single_key
        summary = inspector.SUMMARY.get(table)
        names = [c.name for c in meta.columns]
        shown = names if view.all_columns else list(summary or names[:6])
        visible = ([key] if key else []) + [c for c in shown if c != key]

        return {
            "table": {"name": meta.name, "single_key": key,
                      "note": inspector.TABLE_NOTES.get(table, ""),
                      "columns": _columns_of(meta),
                      "parents": {column: ref[0] for column, ref in meta.parents.items()}},
            "visible": visible,
            "rows": [
                {"key": row[key] if key else None,
                 "cells": {column: _cell(row[column]) for column in visible},
                 "parents": [{"table": ref[0], "id": row[column]}
                             for column, ref in meta.parents.items()
                             if row.get(column) is not None]}
                for row in found
            ],
            "total": total,
            "view": {"page": view.page, "per_page": per_page, "sort": view.sort,
                     "direction": view.direction, "all_columns": view.all_columns,
                     "filters": [{"param": f.param, "label": f.label, "column": f.column,
                                  "op": f.op, "value": f.value} for f in filters]},
            # Adresy z `ListView`, nie sklejane na froncie: „posortuj" ma zachować
            # filtry, a „zdejmij filtr" — sortowanie.
            "links": {
                "canonical": view.url(),
                "clear": f"/inspect/{meta.name}",
                "columns": view.url(all_columns=not view.all_columns, page=1),
                "sort": {column: view.url(sort=column, page=1) for column in names},
                "drop": {f.param: view.url(drop=f, page=1) for f in filters},
                "previous": view.url(page=view.page - 1) if view.page > 1 else None,
                "next": view.url(page=view.page + 1) if view.page * per_page < total else None,
                "per": {str(option): view.url(page=1, per=option)
                        for option in inspector.PER_PAGE_OPTIONS},
            },
            # Ręcznie, nie `asdict`: `is_enum` jest właściwością, a nie polem —
            # a to ona rozstrzyga, czy kolumna dostaje listę, czy pole tekstowe.
            "described": {name: _offer(inspector.offer(cf, active.get(name)))
                          for name, cf in described.items()},
            "operators": {key: list(value) for key, value in inspector.OPERATORS.items()},
            "operator_prefix": inspector.OPERATOR_PREFIX,
            "per_page_options": list(inspector.PER_PAGE_OPTIONS),
            "summary_columns": list(summary) if summary else None,
            "errors": errors,
        }


def _offer(described: inspector.ColumnFilter) -> dict:
    return {"column": described.column.name, "operators": list(described.operators),
            "default": described.default, "is_enum": described.is_enum,
            "options": list(described.options or [])}


@router.get("/{table}/{row_id}")
def record(request: Request, table: str, row_id: int) -> dict:
    with db.connect() as con, con.cursor() as cur:
        sch = inspector.schema(cur)
        meta = _known_table(sch, table)
        if meta.single_key is None:
            raise HTTPException(
                404, f"tabela {table} ma klucz złożony — przeglądaj ją listą z filtrem")
        row = inspector.get_row(cur, sch, table, row_id)
        if row is None:
            raise HTTPException(404, f"nie ma wiersza {table} #{row_id}")
        source = inspector.provenance(cur, table, row)
        return {
            "table": {"name": meta.name, "single_key": meta.single_key,
                      "note": inspector.TABLE_NOTES.get(table, "")},
            "id": row[meta.single_key],
            "row_notes": inspector.row_provenance(table, row),
            "columns": [_record_cell(meta, column, row[column.name])
                        for column in meta.columns],
            "parents": inspector.parents_of(sch, table, row),
            "children": inspector.children_of(cur, sch, table, row),
            "source": asdict(source),
            "crop_name": row.get("path"),
            "pdf_page": inspector.viewed_page(request.query_params.get("_pdfpage"), source),
        }


def _record_cell(table: inspector.Table, column: inspector.Column, value) -> dict:
    """Kolumna wiersza z rodzajem, który rozstrzyga o SPOSOBIE pokazania.

    Rodzaj wychodzi z Pythona, bo tylko tutaj widać prawdziwy typ: po drodze
    przez JSON `bbox` i `jsonb` wyglądają tak samo.
    """
    if value is None:
        kind = "null"
    elif column.name in table.parents:
        kind = "parent"
    elif inspector.is_json(value):
        kind = "json"
    elif column.name in STATUS_COLUMNS:
        kind = "status"
    else:
        kind = "plain"
    return {
        "name": column.name,
        "kind": kind,
        "text": inspector.format_value(value),
        "parent": table.parents[column.name][0] if column.name in table.parents else None,
        "value": value if kind in ("parent", "status") else None,
        "source": inspector.source_of(table.name, column.name),
    }
