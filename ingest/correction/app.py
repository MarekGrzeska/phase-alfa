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

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import psycopg
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

def _started_at(raw: str | None) -> datetime:
    """Moment otwarcia formularza — z ukrytego pola, z sensownym zapasem.

    Liczy się czas PRACY, więc znacznik powstaje przy renderowaniu, a nie przy
    zapisie. Wartość z przyszłości (przestawiony zegar, przeklejony formularz)
    ląduje na „teraz": więz `finished_at >= started_at` ma łapać bzdurę,
    a nie wywalać zapis, którego treść jest w porządku.
    """
    now = datetime.now(timezone.utc)
    if not raw:
        return now
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return now
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return min(parsed, now)


def _scope_query(scope: dict) -> str:
    return urlencode({k: v for k, v in scope.items() if v is not None})


def _friendly(exc: psycopg.Error) -> str:
    """Więz bazy → zdanie dla człowieka. Więzy zostają ostre, komunikaty nie."""
    table = exc.diag.table_name or ""
    if isinstance(exc, psycopg.errors.UniqueViolation):
        # Rozróżnienie po tabeli, a nie jeden komunikat na każdy UNIQUE:
        # zdublowany numer zadania kierowałby wtedy do kryteriów.
        if table == "criterion":
            return ("Dwa progi tego zadania mają tę samą punktację. Więz "
                    "UNIQUE (task_id, points) jest tu celowo — złapał już "
                    "prawdziwy błąd w sondzie. Popraw punktację albo usuń próg.")
        if table == "task":
            return "Ten klucz ma już zadanie o takim numerze."
        return (f"Wiersz łamie unikalność ({exc.diag.constraint_name or 'UNIQUE'})"
                f"{': ' + exc.diag.message_detail if exc.diag.message_detail else ''}")
    if isinstance(exc, psycopg.errors.CheckViolation):
        return ("Wartość poza zakresem, na który pozwala schemat "
                f"({exc.diag.constraint_name or 'CHECK'}).")
    if isinstance(exc, psycopg.DataError):
        # Np. punktacja rzędu 99999: smallint odrzuca ją klasą 22, a nie 23,
        # więc bez tej gałęzi cały formularz przepadał z odpowiedzią 500.
        return ("Liczba jest za duża albo w złym formacie dla tej kolumny "
                f"({exc.diag.message_primary or exc}).")
    return exc.diag.message_primary or str(exc)


def _overlay(task: dict, form: Mapping[str, str]) -> None:
    """Po nieudanej walidacji formularz wraca z tym, co człowiek wpisał.

    Bez tego jedno puste pole wymagane kasuje wszystkie pozostałe poprawki —
    czyli kara za literówkę jest wielokrotnie większa niż literówka.
    """
    for column in ("number", "max_points", "kind"):
        if f"task.{column}" in form:
            task[column] = form[f"task.{column}"]
    for version in task["versions"]:
        key = f"version.{version['id']}.content"
        if key in form:
            version["content"] = form[key]
        for answer in version["answers"]:
            key = f"answer.{answer['id']}.answer"
            if key in form:
                answer["answer"] = form[key]
    for asset in task["assets"]:
        for name in assets.BOX_FIELDS:
            key = f"asset.{asset['id']}.{name}"
            if key in form:
                asset["box"][name] = form[key]
        key = f"asset.{asset['id']}.page"
        if key in form:
            asset["page"] = form[key]
    for criterion in task["criteria"]:
        for column in ("points", "label", "description"):
            key = f"criterion.{criterion['id']}.{column}"
            if key in form:
                criterion[column] = form[key]
        for condition in criterion["conditions"]:
            key = f"condition.{condition['id']}.description"
            if key in form:
                condition["description"] = form[key]
            for expression in condition["expressions"]:
                key = f"expression.{expression['id']}.expression"
                if key in form:
                    expression["expression"] = form[key]


def _render_task(request: Request, cur, task: dict, started_at: datetime,
                 errors: list[str], page: int | None = None,
                 edited_before: bool = False, scope: dict | None = None,
                 status_code: int = 200) -> HTMLResponse:
    source = db.page_source(cur, task["id"]) or {}
    scope = scope or db.parse_scope()
    return templates.TemplateResponse(
        request,
        "task.html",
        {
            "task": task,
            "nav": db.neighbours(cur, task),
            "requirements": db.available_requirements(cur, task["id"]),
            "started_at": started_at.isoformat(),
            "errors": errors,
            # Podgląd chodzi po stronach klucza, więc numer strony jest stanem
            # widoku — w adresie, nie w JavaScripcie.
            "page": page or task["page"],
            "document_pages": source.get("pages"),
            "edited_before": edited_before,
            "scope": scope,
            "scope_query": _scope_query(scope),
        },
        status_code=status_code,
    )


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
def task_form(request: Request, task_id: int, started_at: str | None = None,
              page: int | None = None, edited_before: str = "",
              year: str = "", code: str = "", variant: str = "") -> HTMLResponse:
    with db.connect() as con, con.cursor() as cur:
        task = db.load_task(cur, task_id)
        if task is None:
            raise HTTPException(404, f"nie ma zadania {task_id}")
        return _render_task(request, cur, task, _started_at(started_at),
                            errors=[], page=page,
                            edited_before=edited_before == "1",
                            scope=db.parse_scope(year, code, variant))


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


@app.post("/task/{task_id}")
async def task_save(request: Request, task_id: int):
    # Ekran nie ma uwierzytelnienia, bo stoi na 127.0.0.1 — ale „na localhoście"
    # nie znaczy „tylko my": każda inna strona otwarta w tej przeglądarce może
    # wysłać tu formularz i zatwierdzić zadanie. Nagłówek `Sec-Fetch-Site` wysyłają
    # wszystkie dzisiejsze przeglądarki; jego brak (curl, stary klient) przepuszczamy,
    # bo bramka ma odciąć cudzą STRONĘ, a nie narzędzia z konsoli.
    origin = request.headers.get("sec-fetch-site", "same-origin")
    if origin != "same-origin":
        raise HTTPException(403, f"żądanie spoza ekranu korekty (sec-fetch-site: {origin})")

    form = dict(await request.form())
    action = str(form.get("action", ""))
    started_at = _started_at(str(form.get("started_at") or ""))
    shown_page = str(form.get("page") or "")
    shown_page = int(shown_page) if shown_page.isdigit() else None
    # Poprawki zapisane wcześniej w tej samej rundzie (dokładanie wiersza robi
    # zapis i przekierowanie). Bez tego zadanie poprawione, a zatwierdzone
    # dopiero po dołożeniu progu, wchodziło do statystyki jako trafienie parsera.
    edited_before = str(form.get("edited_before") or "") == "1"
    scope = db.parse_scope(str(form.get("year") or ""), str(form.get("code") or ""),
                   str(form.get("variant") or ""))
    scope_query = _scope_query(scope)

    con = db.connect()
    try:
        try:
            # `con.transaction()`, a NIE `with con`: w psycopg3 kontekst połączenia
            # nie tylko domyka transakcję, ale i ZAMYKA połączenie — a tutaj jest
            # ono potrzebne dalej, do ponownego wyrenderowania formularza z błędami.
            # Wycofanie jest tu warunkiem poprawności, nie ostrożnością: `save()`
            # rzuca PO skasowaniu zaznaczonych wierszy.
            with con.transaction(), con.cursor() as cur:
                if db.load_task(cur, task_id) is None:
                    raise HTTPException(404, f"nie ma zadania {task_id}")
                changes = db.save(cur, task_id, form)
                if action in ("crop", "save"):
                    # Ramkę dociąga się na raty: wpisz, obejrzyj wycinek, popraw.
                    # Rozstrzygnięcia tu NIE MA — `db.save` już wyciął plik,
                    # a formularz wraca z tym samym `started_at`, żeby pomiar S8
                    # liczył czas pracy nad zadaniem, a nie od ostatniego cięcia.
                    # `save` to ta sama droga bez ramki: Enter w polu i „Zapisz,
                    # zostań" — inaczej Enter trafiał w pierwszy przycisk formularza.
                    target = f"/task/{task_id}?" + urlencode(
                        {"started_at": started_at.isoformat(),
                         # Usunięcia liczą się tak samo jak edycje: skasowany
                         # próg to poprawka, a nie trafienie parsera.
                         **({"edited_before": "1"}
                            if edited_before or changes["edited"]
                            or changes["deleted"] else {}),
                         **({"page": shown_page} if shown_page else {}),
                         **{k: v for k, v in scope.items() if v is not None}})
                elif action.startswith("add:"):
                    _add_row(cur, task_id, action)
                    # Przekierowanie, nie render: odświeżenie strony po dodaniu
                    # wiersza nie ma dokładać kolejnego. `started_at` jedzie
                    # w adresie, żeby pomiar czasu liczył się od otwarcia
                    # zadania, a nie od ostatniego kliknięcia.
                    target = f"/task/{task_id}?" + urlencode(
                        {"started_at": started_at.isoformat(),
                         "edited_before": "1",
                         **({"page": shown_page} if shown_page else {}),
                         **{k: v for k, v in scope.items() if v is not None}})
                else:
                    db.decide(cur, task_id, action, started_at, changes,
                              edited_before=edited_before)
                    target = (f"/task/{task_id}" if action == "reopen" else "/next")
                    if scope_query:
                        target += f"?{scope_query}"
        except (db.ValidationError, psycopg.IntegrityError, psycopg.DataError) as exc:
            messages = (exc.messages if isinstance(exc, db.ValidationError)
                        else [_friendly(exc)])
            with con.cursor() as cur:
                task = db.load_task(cur, task_id)
                if task is None:
                    raise HTTPException(404, f"nie ma zadania {task_id}") from exc
                _overlay(task, form)
                return _render_task(request, cur, task, started_at, messages,
                                    page=shown_page, edited_before=edited_before,
                                    scope=scope, status_code=422)
        return RedirectResponse(target, status_code=303)
    finally:
        con.close()


def _add_row(cur, task_id: int, action: str) -> None:
    """`add:criterion`, `add:condition:12`, `add:expression:34`."""
    parts = action.split(":")
    what = parts[1] if len(parts) > 1 else ""
    parent = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if what == "criterion":
        db.add_criterion(cur, task_id)
    elif what == "condition" and parent:
        db.add_condition(cur, task_id, parent)
    elif what == "expression" and parent:
        db.add_expression(cur, task_id, parent)
    else:
        raise db.ValidationError([f"Nieznane polecenie: [{action}]."])


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
