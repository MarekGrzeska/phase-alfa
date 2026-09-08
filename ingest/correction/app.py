"""Ekran korekty — FastAPI, widoki w trakcie migracji z Jinja2 na Reacta.

Narzędzie na trzy tygodnie pracy jednej osoby na localhoście. Reguła stopu
z Planu Implementacji obowiązuje tu podwójnie: widok jest zrobiony, gdy
odpowiada na pytanie, dla którego powstał. Każda godzina w stylach tego ekranu
jest godziną zdjętą z korekty, a to korekta jest ścieżką krytyczną A2.

Front stoi w `ui/` (React + Vite, build do `static/`). Migracja idzie ekranami:
dziś Reactem jest panel agenta doklejony do stron Jinja, dalej pójdą kolejne
widoki. Do czasu jej domknięcia oba sposoby renderowania są tu naraz — i to
jest stan przejściowy, a nie docelowa architektura.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from correction import api, assets, db, inspector, pages
from pdf import crop as crop_pdf

app = FastAPI(title="Klucz — ekran korekty", docs_url=None, redoc_url=None)

# Front z `ui/` (React) po zbudowaniu — `task correction:ui`. Katalog powstaje
# dopiero z buildu, więc `check_dir=False`: brak paczki ma zabrać panel agenta,
# a nie wywalić cały ekran korekty przy starcie.
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC), check_dir=False), name="static")

app.include_router(api.router)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["STATUS_LABELS"] = db.STATUS_LABELS
templates.env.globals["TASK_KINDS"] = db.TASK_KINDS


# ------------------------------------------------------------------ pomocnicze

def _scope_query(scope: dict) -> str:
    return urlencode({k: v for k, v in scope.items() if v is not None})


# ----------------------------------------------------------------------- trasy

@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Przegląd korekty. Widok rysuje React, dane bierze z `/api/overview`.

    Filtry NIE są tu czytane: ten sam adres z parametrami czyta front i podaje
    je zapytaniu. Serwer oddaje tylko skorupę, więc nie ma dwóch miejsc,
    w których „pusty rocznik" znaczy coś innego.
    """
    return templates.TemplateResponse(
        request, "app.html", {"title": "Postęp korekty", "view": "overview"})


@app.get("/next")
def next_task(year: str = "", code: str = "", variant: str = "") -> RedirectResponse:
    """Wejście do pracy: pierwsze nierozstrzygnięte zadanie w kolejności arkuszy."""
    scope = db.parse_scope(year, code, variant)
    with db.connect() as con, con.cursor() as cur:
        task_id = db.next_pending(cur, **scope)
    query = _scope_query(scope)
    if task_id is None:
        return RedirectResponse(f"/?{query}" if query else "/", status_code=303)
    return RedirectResponse(f"/task/{task_id}" + (f"?{query}" if query else ""),
                            status_code=303)


@app.get("/task/{task_id}", response_class=HTMLResponse)
def task_form(request: Request, task_id: int) -> HTMLResponse:
    """Formularz korekty. Widok rysuje React, dane bierze z `/api/task/{id}`.

    Istnienie zadania sprawdzamy TUTAJ: adres z ręki albo ze starej zakładki ma
    dać 404 od razu, a nie pustą skorupę, która dopiero po chwili powie, że nie
    ma czego korygować.
    """
    with db.connect() as con, con.cursor() as cur:
        if db.load_task(cur, task_id) is None:
            raise HTTPException(404, f"nie ma zadania {task_id}")
    return templates.TemplateResponse(
        request, "app.html", {"title": f"Zadanie {task_id}", "view": "task"})


@app.get("/task/{task_id}/page.png")
def task_page(task_id: int, n: int | None = None) -> FileResponse:
    with db.connect() as con, con.cursor() as cur:
        source = db.page_source(cur, task_id)
    if source is None:
        raise HTTPException(404, f"nie ma zadania {task_id}")
    page = n or source["page"]
    if not page:
        raise HTTPException(
            404,
            "to zadanie nie ma zapisanej strony w kluczu — klucz wczytano razem "
            "z arkuszami przed migracją 0004. Przeładuj go: task ingest",
        )
    try:
        return FileResponse(pages.render(source["path"], page), media_type="image/png")
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e


@app.get("/asset/{asset_id}.png")
def asset_crop(asset_id: int) -> FileResponse:
    """Wycinek z bloba — to, co zobaczy przeglądarka korpusu (W2)."""
    with db.connect() as con, con.cursor() as cur:
        asset = assets.source(cur, asset_id)
    if asset is None:
        raise HTTPException(404, f"nie ma zasobu {asset_id}")
    try:
        path = crop_pdf.target_path(asset["path"])
    except crop_pdf.CropError as e:
        raise HTTPException(404, str(e)) from e
    if not path.exists():
        raise HTTPException(404, "ten zasób nie ma jeszcze wycinka — dociągnij ramkę")
    return FileResponse(path, media_type="image/png")


@app.get("/asset/{asset_id}/page.png")
def asset_page(asset_id: int, n: int | None = None, grid: str = "1") -> FileResponse:
    """Strona ZESZYTU ZADAŃ, z której tnie się wycinek — domyślnie z siatką."""
    with db.connect() as con, con.cursor() as cur:
        asset = assets.source(cur, asset_id)
    if asset is None:
        raise HTTPException(404, f"nie ma zasobu {asset_id}")
    if asset["paper_path"] is None:
        raise HTTPException(
            404,
            "ta wersja zadania nie ma w bazie zeszytu zadań — przeładuj klucz "
            "poleceniem `task ingest -- --with-papers`",
        )
    try:
        return FileResponse(
            pages.render(asset["paper_path"], n or asset["page"], grid=grid == "1"),
            media_type="image/png")
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e


# ------------------------------------------------------------------ inspektor
# Tylko odczyt. Nazwa tabeli z adresu przechodzi przez allowlistę ze schematu,
# a nieznana kończy się 404 — nie ma drogi z URL-a do tekstu SQL-a.

templates.env.globals["format_value"] = inspector.format_value
templates.env.globals["is_json"] = inspector.is_json
templates.env.globals["source_of"] = inspector.source_of


def _known_table(sch: inspector.Schema, name: str) -> inspector.Table:
    if name not in sch:
        raise HTTPException(404, f"nie ma takiej tabeli: {name}")
    return sch.tables[name]


@app.get("/inspect", response_class=HTMLResponse)
def inspect_index(request: Request) -> HTMLResponse:
    with db.connect() as con, con.cursor() as cur:
        sch = inspector.schema(cur)
        return templates.TemplateResponse(
            request, "inspect_index.html",
            {"schema": sch, "counts": inspector.counts(cur, sch),
             "notes": inspector.TABLE_NOTES, "health": inspector.health(cur),
             "empty_columns": inspector.empty_columns(cur), "scope_query": ""},
        )


@app.get("/inspect/health/{key}", response_class=HTMLResponse)
def inspect_health(request: Request, key: str) -> HTMLResponse:
    check = inspector.CHECK_BY_KEY.get(key)
    if check is None:
        raise HTTPException(404, f"nie ma takiej kontroli: {key}")
    with db.connect() as con, con.cursor() as cur:
        sch = inspector.schema(cur)
        rows = inspector.run_check(cur, check)
        return templates.TemplateResponse(
            request, "inspect_health.html",
            {"check": check, "rows": rows, "table": sch.tables.get(check.table),
             "columns": list(rows[0].keys()) if rows else [], "scope_query": ""},
        )


@app.get("/inspect/document/{document_id}.pdf")
def inspect_pdf(document_id: int) -> FileResponse:
    with db.connect() as con, con.cursor() as cur:
        cur.execute("SELECT path FROM document WHERE id = %s", (document_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, f"nie ma dokumentu {document_id}")
    try:
        path = pages.source_pdf(row["path"])
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e
    if not path.exists():
        raise HTTPException(404, f"pliku nie ma w mirrorze: {row['path']}")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/inspect/document/{document_id}/page/{n}.png")
def inspect_page(document_id: int, n: int) -> FileResponse:
    with db.connect() as con, con.cursor() as cur:
        cur.execute("SELECT path FROM document WHERE id = %s", (document_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, f"nie ma dokumentu {document_id}")
    try:
        return FileResponse(pages.render(row["path"], n), media_type="image/png")
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e


@app.get("/inspect/{table}", response_class=HTMLResponse)
def inspect_list(request: Request, table: str) -> Response:
    # Stan widoku czytany z `query_params`, a NIE przez parametry funkcji: FastAPI
    # odrzuciłby `_page=` pustym stringiem z 422, a wiersz filtrów wysyła puste pola
    # przy każdym wysłaniu formularza. Tu pusta wartość ma znaczyć „domyślna".
    params = request.query_params
    sort = params.get("_sort") or ""
    raw_page = params.get("_page") or ""
    chosen_per = params.get("_per")
    per_page = inspector.per_page_or_default(
        chosen_per if chosen_per is not None else request.cookies.get(inspector.PER_PAGE_COOKIE))
    with db.connect() as con, con.cursor() as cur:
        sch = inspector.schema(cur)
        meta = _known_table(sch, table)
        filters, rejected, from_form = inspector.parse_filters(meta, params.multi_items())

        view = inspector.ListView(
            table=meta, filters=filters,
            sort=sort if meta.has_column(sort) else None,
            direction="desc" if params.get("_dir") == "desc" else "asc",
            all_columns=params.get("_cols") == "all",
            page=int(raw_page) if raw_page.isdigit() and int(raw_page) > 0 else 1,
            per_page=per_page,
        )

        # Wiersz filtrów przysyła wartość i operator osobno, bo pole nie umie zmienić
        # swojej nazwy bez JavaScriptu. Zamiana na postać kanoniczną i 303: adres
        # w pasku da się skopiować, a „wstecz" nie wraca do wysłanego formularza.
        # Rozmiar strony wraca tą samą drogą: `_per` z adresu ląduje w ciasteczku
        # i znika, a strona wraca na pierwszą — przy 25 na stronie „strona 12"
        # potrafiłaby być już za końcem listy.
        if from_form or chosen_per is not None:
            response = RedirectResponse(view.url(page=1), status_code=303)
            if chosen_per is not None:
                response.set_cookie(inspector.PER_PAGE_COOKIE, str(per_page),
                                    max_age=inspector.PER_PAGE_MAX_AGE, path="/inspect",
                                    httponly=True, samesite="lax")
            return response

        errors = []
        if rejected:
            errors.append("Filtr po nieznanej kolumnie albo operatorze, pominięty: "
                          + ", ".join(rejected))
        try:
            rows, total = inspector.list_rows(cur, sch, table, filters, view.sort,
                                              view.direction, view.page, per_page)
        except inspector.FilterError as e:
            # Odrzucone zapytanie zrywa transakcję: bez wycofania każde następne
            # (choćby podpowiedzi do formularza) wraca z „current transaction is
            # aborted", czyli literówka w filtrze kończy się pięćsetką mimo gałęzi obok.
            con.rollback()
            rows, total = [], 0
            errors.append(str(e))

        hints = inspector.suggestions(cur, meta)
        active = {f.column: f for f in filters}
        described = inspector.column_filters(meta, sch.enums.get(table, {}), hints,
                                             inspector.table_size(cur, table))
        return templates.TemplateResponse(
            request, "inspect_list.html",
            {"table": meta, "rows": rows, "total": total, "view": view,
             "operators": inspector.OPERATORS,
             "operator_prefix": inspector.OPERATOR_PREFIX,
             "active": active,
             "described": {name: inspector.offer(cf, active.get(name))
                           for name, cf in described.items()},
             "errors": errors, "per_page": per_page,
             "per_page_options": inspector.PER_PAGE_OPTIONS,
             "note": inspector.TABLE_NOTES.get(table, ""),
             "summary_columns": inspector.SUMMARY.get(table), "scope_query": ""},
        )


@app.get("/inspect/{table}/{row_id}", response_class=HTMLResponse)
def inspect_record(request: Request, table: str, row_id: int) -> HTMLResponse:
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
        return templates.TemplateResponse(
            request, "inspect_record.html",
            {"table": meta, "row": row, "note": inspector.TABLE_NOTES.get(table, ""),
             "row_notes": inspector.row_provenance(table, row),
             "parents": inspector.parents_of(sch, table, row),
             "children": inspector.children_of(cur, sch, table, row),
             "source": source,
             "pdf_page": inspector.viewed_page(request.query_params.get("_pdfpage"), source),
             "scope_query": ""},
        )
