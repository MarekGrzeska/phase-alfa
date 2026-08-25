"""Ekran korekty — FastAPI + Jinja2, bez kroku budowania i bez frameworka na froncie.

Narzędzie na trzy tygodnie pracy jednej osoby na localhoście. Reguła stopu
z Planu Implementacji obowiązuje tu podwójnie: widok jest zrobiony, gdy
odpowiada na pytanie, dla którego powstał. Każda godzina w stylach tego ekranu
jest godziną zdjętą z korekty, a to korekta jest ścieżką krytyczną A2.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from correction import db, pages, stats

app = FastAPI(title="Klucz — ekran korekty", docs_url=None, redoc_url=None)
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
                 edited_before: bool = False,
                 status_code: int = 200) -> HTMLResponse:
    source = db.page_source(cur, task["id"]) or {}
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
        },
        status_code=status_code,
    )


# ----------------------------------------------------------------------- trasy

@app.get("/", response_class=HTMLResponse)
def index(request: Request, status: str = "", year: str = "",
          code: str = "") -> HTMLResponse:
    # Wszystkie trzy filtry przyjmują TEKST i puste znaczy „wszystkie" — bo tak
    # wygląda opcja „wszystkie" w formularzu obok. Przy `year: int | None`
    # własny formularz tej strony wracał z 422, a `status` spoza listy z 400:
    # jedyny sposób na filtrowanie był ustawić wszystkie trzy naraz.
    if status and status not in db.STATUSES:
        raise HTTPException(400, f"nieznany status: {status}")
    with db.connect() as con, con.cursor() as cur:
        selected = {"status": status or None,
                    "year": int(year) if year.isdigit() else None,
                    "code": code or None}
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "numbers": stats.collect(cur),
                "tasks": db.list_tasks(cur, **selected),
                "options": db.filters(cur),
                "selected": selected,
                "next_id": db.next_pending(cur),
            },
        )


@app.get("/next")
def next_task() -> RedirectResponse:
    """Wejście do pracy: pierwsze nierozstrzygnięte zadanie w kolejności arkuszy."""
    with db.connect() as con, con.cursor() as cur:
        task_id = db.next_pending(cur)
    return RedirectResponse(f"/task/{task_id}" if task_id else "/", status_code=303)


@app.get("/task/{task_id}", response_class=HTMLResponse)
def task_form(request: Request, task_id: int, started_at: str | None = None,
              page: int | None = None, edited_before: str = "") -> HTMLResponse:
    with db.connect() as con, con.cursor() as cur:
        task = db.load_task(cur, task_id)
        if task is None:
            raise HTTPException(404, f"nie ma zadania {task_id}")
        return _render_task(request, cur, task, _started_at(started_at),
                            errors=[], page=page,
                            edited_before=edited_before == "1")


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
                if action.startswith("add:"):
                    _add_row(cur, task_id, action)
                    # Przekierowanie, nie render: odświeżenie strony po dodaniu
                    # wiersza nie ma dokładać kolejnego. `started_at` jedzie
                    # w adresie, żeby pomiar czasu liczył się od otwarcia
                    # zadania, a nie od ostatniego kliknięcia.
                    target = f"/task/{task_id}?" + urlencode(
                        {"started_at": started_at.isoformat(),
                         "edited_before": "1",
                         **({"page": shown_page} if shown_page else {})})
                else:
                    db.decide(cur, task_id, action, started_at, changes,
                              edited_before=edited_before)
                    target = f"/task/{task_id}" if action == "reopen" else "/next"
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
                                    status_code=422)
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
