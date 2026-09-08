"""JSON dla frontu ekranu korekty — dane bez HTML-a wokół nich.

Trasy `/api/*` powstają w miarę, jak kolejne ekrany przechodzą na Reacta.
Kształt odpowiedzi jest ten sam, co kontekst szablonu, który zastąpiła:
migracja ma zmienić SPOSÓB rysowania widoku, a nie to, co widok pokazuje.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

import psycopg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from correction import db, stats

router = APIRouter(prefix="/api")


@router.get("/overview")
def overview(status: str = "", year: str = "", code: str = "",
             variant: str = "") -> dict:
    """Przegląd korekty: liczby S8, zakres do wyboru i lista zadań."""
    if status and status not in db.STATUSES:
        raise HTTPException(400, f"nieznany status: {status}")
    scope = db.parse_scope(year, code, variant)
    with db.connect() as con, con.cursor() as cur:
        return {
            "numbers": stats.collect(cur),
            "tasks": db.list_tasks(cur, status=status or None, **scope),
            "options": db.filters(cur),
            "selected": {"status": status or None, **scope},
            "next_id": db.next_pending(cur, **scope),
            # Etykiety statusów jadą z bazy razem z danymi: gdyby front trzymał
            # własną kopię, „poprawione" znaczyłoby co innego po każdej zmianie
            # słownika w `db.py`.
            "status_labels": db.STATUS_LABELS,
        }


# --------------------------------------------------------------- jedno zadanie

class ScopeIn(BaseModel):
    """Zakres pracy w postaci, w jakiej przyszedł z adresu — tekstem."""

    year: str = ""
    code: str = ""
    variant: str = ""


class TaskSave(BaseModel):
    """Zapis formularza korekty.

    `fields` to płaskie pary nazwa→wartość, dokładnie te, które wysyłał
    formularz HTML (`criterion.12.points`, `delete.answer.3`). Kształt został
    celowo: rozstrzyga o nim `db.save`, a migracja frontu nie ma prawa przy
    okazji zmieniać reguł zapisu do korpusu.
    """

    action: str
    started_at: str | None = None
    page: int | None = None
    edited_before: bool = False
    scope: ScopeIn = ScopeIn()
    fields: dict[str, str] = {}


def started_at_of(raw: str | None) -> datetime:
    """Moment otwarcia formularza — z pola, które dostał front, z zapasem.

    Liczy się czas PRACY, więc znacznik powstaje przy wydaniu zadania, a nie
    przy zapisie. Wartość z przyszłości (przestawiony zegar, przeklejony
    formularz) ląduje na „teraz": więz `finished_at >= started_at` ma łapać
    bzdurę, a nie wywalać zapis, którego treść jest w porządku.
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


def friendly_error(exc: psycopg.Error) -> str:
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


def _task_payload(cur, task: dict, started_at: datetime,
                  page: int | None = None) -> dict:
    """Komplet, z którego front rysuje formularz — bez HTML-a wokół niego."""
    source = db.page_source(cur, task["id"]) or {}
    return {
        "task": task,
        "nav": db.neighbours(cur, task),
        "requirements": db.available_requirements(cur, task["id"]),
        "started_at": started_at.isoformat(),
        # Podgląd chodzi po stronach klucza, więc numer strony jest stanem
        # widoku — w adresie, nie w pamięci komponentu.
        "page": page or task["page"],
        "document_pages": source.get("pages"),
        "status_labels": db.STATUS_LABELS,
        "task_kinds": list(db.TASK_KINDS),
    }


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


@router.get("/task/{task_id}")
def task_detail(task_id: int, page: int | None = None) -> dict:
    """Zadanie do korekty. Zegar S8 rusza tutaj — przy WYDANIU formularza."""
    with db.connect() as con, con.cursor() as cur:
        task = db.load_task(cur, task_id)
        if task is None:
            raise HTTPException(404, f"nie ma zadania {task_id}")
        return _task_payload(cur, task, datetime.now(timezone.utc), page)


@router.post("/task/{task_id}")
def task_save(request: Request, task_id: int, payload: TaskSave):
    """Zapis, dołożenie wiersza, wycięcie ramki albo rozstrzygnięcie.

    Rozstrzygnięcie odsyła `redirect` — dokąd iść dalej, wie serwer, bo to on
    zna kolejność arkuszy i zakres pracy. Reszta działań odsyła świeże zadanie:
    dokładanie progu ma zostawić korektora tam, gdzie był.
    """
    # Ekran nie ma uwierzytelnienia, bo stoi na 127.0.0.1 — ale „na localhoście"
    # nie znaczy „tylko my": każda inna strona otwarta w tej przeglądarce może
    # wysłać tu zapis i zatwierdzić zadanie. Nagłówek `Sec-Fetch-Site` wysyłają
    # wszystkie dzisiejsze przeglądarki; jego brak (curl, stary klient)
    # przepuszczamy, bo bramka ma odciąć cudzą STRONĘ, a nie konsolę.
    origin = request.headers.get("sec-fetch-site", "same-origin")
    if origin != "same-origin":
        raise HTTPException(403, f"żądanie spoza ekranu korekty (sec-fetch-site: {origin})")

    action = payload.action
    started_at = started_at_of(payload.started_at)
    scope = db.parse_scope(payload.scope.year, payload.scope.code, payload.scope.variant)
    scope_query = urlencode({k: v for k, v in scope.items() if v is not None})

    con = db.connect()
    try:
        try:
            # `con.transaction()`, a NIE `with con`: w psycopg3 kontekst połączenia
            # nie tylko domyka transakcję, ale i ZAMYKA połączenie — a jest ono
            # potrzebne dalej, do odesłania świeżego zadania. Wycofanie jest tu
            # warunkiem poprawności, nie ostrożnością: `save()` rzuca PO skasowaniu
            # zaznaczonych wierszy.
            with con.transaction(), con.cursor() as cur:
                if db.load_task(cur, task_id) is None:
                    raise HTTPException(404, f"nie ma zadania {task_id}")
                changes = db.save(cur, task_id, payload.fields)
                if action in ("crop", "save"):
                    # Ramkę dociąga się na raty: wpisz, obejrzyj wycinek, popraw.
                    # Usunięcia liczą się tak samo jak edycje: skasowany próg to
                    # poprawka, a nie trafienie parsera.
                    edited = (payload.edited_before or bool(changes["edited"])
                              or bool(changes["deleted"]))
                    target = None
                elif action.startswith("add:"):
                    _add_row(cur, task_id, action)
                    edited = True
                    target = None
                else:
                    db.decide(cur, task_id, action, started_at, changes,
                              edited_before=payload.edited_before)
                    edited = payload.edited_before
                    target = (f"/task/{task_id}" if action == "reopen" else "/next")
                    if scope_query:
                        target += f"?{scope_query}"
        except (db.ValidationError, psycopg.IntegrityError, psycopg.DataError) as exc:
            messages = (exc.messages if isinstance(exc, db.ValidationError)
                        else [friendly_error(exc)])
            # 422 z powodami, a formularz zostaje u człowieka: zadania z bazy
            # NIE odsyłamy, bo nadpisałoby to, co właśnie wpisał.
            return JSONResponse({"errors": messages}, status_code=422)

        if target is not None:
            return {"redirect": target}
        with con.cursor() as cur:
            task = db.load_task(cur, task_id)
            if task is None:
                raise HTTPException(404, f"nie ma zadania {task_id}")
            # `started_at` wraca TEN SAM, z którym przyszedł zapis: pomiar S8
            # liczy czas pracy nad zadaniem, a nie od ostatniego cięcia ramki.
            return {**_task_payload(cur, task, started_at, payload.page),
                    "edited_before": edited}
    finally:
        con.close()
