"""Korpus: odczyt zadania w kształcie formularza i zapis TĄ SAMĄ drogą, co człowiek.

`task_save` i `task_decide` wołają `db.save` i `db.decide` — więc status wychodzi
z porównania z bazą, więzy odrzucają śmieci agenta jak śmieci parsera, a dziennik
`correction_event` niesie `actor = 'agent'`. Rekord, który już jest korpusem
(`approved`/`corrected`), wolno zmienić dopiero po zgodzie człowieka;
rozstrzygnięcie zawsze wymaga zgody.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations

from agent import audit, confirm, context, limits, urls
from correction import api as correction_api
from correction import assets, db, pages

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False,
                         openWorldHint=False)
CONFIRMED = {"confirm": True}

IN_CORPUS = ("approved", "corrected")
ACTIONS = ("approve", "reject", "reopen")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(cur, task_id: int) -> dict:
    task = db.load_task(cur, task_id)
    if task is None:
        raise ValueError(f"nie ma zadania {task_id}")
    return task


def _write_error(exc: Exception) -> ValueError:
    if isinstance(exc, db.ValidationError):
        return ValueError("; ".join(exc.messages))
    if isinstance(exc, psycopg.Error):
        return ValueError(correction_api.friendly_error(exc))
    return ValueError(str(exc))


def _fields_preview(fields: dict[str, str]) -> str:
    return "\n".join(f"{k} = {v!r}" for k, v in sorted(fields.items()))


def _task_url(task_id: int) -> str:
    return urls.build({"view": "task", "id": task_id})


def _task_of_asset(cur, asset_id: int) -> int:
    cur.execute("SELECT tv.task_id FROM asset a JOIN task_version tv ON tv.id = a.task_version_id "
                "WHERE a.id = %s", (asset_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"nie ma zasobu {asset_id}")
    return row["task_id"]


def save_fields(con, task_id: int, fields: dict[str, str], tool: str, arguments: dict,
                confirmation: int | None, title: str) -> dict:
    """Wspólna droga `task_save`, `asset_frame`, `asset_describe`: zgoda, `db.save`, dziennik."""
    if not fields:
        raise ValueError("puste `fields` — nie ma czego zapisać")
    try:
        with con.transaction(), con.cursor() as cur:
            task = _load(cur, task_id)
            if task["review_status"] in IN_CORPUS:
                asked = confirm.ensure(cur, confirmation, tool, arguments, title,
                                       f"zadanie #{task_id} jest w korpusie "
                                       f"({task['review_status']})\n{_fields_preview(fields)}")
                if asked is not None:
                    return asked
            changes = db.save(cur, task_id, fields)
            audit.record(cur, tool, arguments, changes, confirmation_id=confirmation)
    except (db.ValidationError, psycopg.IntegrityError, psycopg.DataError) as exc:
        raise _write_error(exc) from exc
    return {"task_id": task_id, "changes": limits.jsonable(changes),
            "review_status": task["review_status"], "url": _task_url(task_id),
            "note": ("status zadania nie zmienił się — rozstrzyga go `task_decide`"
                     if task["review_status"] == "pending" else
                     "rekord w korpusie zmieniony za zgodą człowieka")}


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def task_get(id: int, page: int | None = None) -> dict:
        """Zadanie w kształcie formularza korekty: numer, pula, rodzaj, wersje z treścią
        i odpowiedziami wzorcowymi, progi → warunki → zapisy, wymagania, zasoby
        (ramka, opis), podpowiedzi prefill, uwagi modelu z `verify`, sąsiedzi w kluczu.

        Identyfikatory wierszy z tej odpowiedzi są nazwami pól dla `task_save`
        (`criterion.<id>.points`). `url` prowadzi do formularza.
        """
        with db.connect() as con, con.cursor() as cur:
            task = _load(cur, id)
            return limits.jsonable({
                "task": task,
                "nav": db.neighbours(cur, task),
                "available_requirements": db.available_requirements(cur, id),
                "page": page or task["page"],
                "document_pages": task["document_pages"],
                "url": _task_url(id),
                "field_names": {
                    "task": ["task.number", "task.max_points", "task.kind"],
                    "rows": ["version.<id>.content", "answer.<id>.answer",
                             "criterion.<id>.points|label|description",
                             "condition.<id>.description", "expression.<id>.expression",
                             "asset.<id>.page|x0|top|x1|bottom|description"],
                    "delete": ["delete.answer.<id>", "delete.criterion.<id>",
                               "delete.condition.<id>", "delete.expression.<id>",
                               "delete.requirement.<id>"],
                    "requirements": ["add_requirement = <requirement id>"],
                },
            })

    @mcp.tool(annotations=READ_ONLY)
    def task_find(status: str | None = None, year: int | None = None,
                  code: str | None = None, variant: str | None = None,
                  kind: str | None = None, limit: int = 50) -> dict:
        """Zadania w zakresie (rocznik, kod arkusza, wariant), opcjonalnie po statusie
        (pending, approved, corrected, rejected) i rodzaju (closed, open_short,
        open_extended, essay). `next_pending` = pierwsze nierozstrzygnięte w zakresie."""
        if status and status not in db.STATUSES:
            raise ValueError(f"nieznany status {status!r}; znane: {', '.join(db.STATUSES)}")
        if kind and kind not in db.TASK_KINDS:
            raise ValueError(f"nieznany rodzaj {kind!r}; znane: {', '.join(db.TASK_KINDS)}")
        limit = max(1, min(int(limit), limits.MAX_ROWS))
        with db.connect() as con, con.cursor() as cur:
            # Rodzaj filtrujemy po stronie Pythona, więc pytamy o zapas wierszy.
            rows = db.list_tasks(cur, status or None, year, code, variant,
                                 limit=limit * (3 if kind else 1))
            if kind:
                rows = [r for r in rows if r["kind"] == kind][:limit]
            return {"tasks": limits.jsonable([{**r, "url": _task_url(r["id"])} for r in rows]),
                    "count": len(rows),
                    "next_pending": db.next_pending(cur, year, code, variant),
                    "url": urls.build({"view": "overview", "status": status or None,
                                       "scope": {"year": year, "code": code,
                                                 "variant": variant}})}

    @mcp.tool(annotations=WRITES, meta=CONFIRMED)
    def task_save(id: int, fields: dict[str, str], confirmation: int | None = None) -> dict:
        """Zapisz pola formularza korekty — dokładnie tą drogą, którą zapisuje człowiek.

        `fields` to płaskie pary nazwa→tekst z `task_get.field_names`, np.
        {"criterion.12.points": "2", "delete.condition.7": "1"}. Zmiany liczy `db.save`
        przez porównanie z bazą; więzy schematu (UNIQUE punktacji, zakresy) odrzucają
        zapis z komunikatem — nie luzuj ich, popraw dane. Status zadania zostaje;
        rozstrzyga `task_decide`. Zadanie już w korpusie wymaga zgody człowieka
        (`confirmation`).
        """
        arguments = {"id": id, "fields": fields}
        with db.connect() as con:
            return save_fields(con, id, fields, "task_save", arguments, confirmation,
                               f"Zmiana rekordu w korpusie: zadanie #{id}")

    @mcp.tool(annotations=WRITES, meta=CONFIRMED)
    def task_add_row(id: int, what: str, parent: int | None = None,
                     confirmation: int | None = None) -> dict:
        """Nowy próg (`what='criterion'`), warunek (`'condition'`, `parent`=id progu)
        albo zapis równoważny (`'expression'`, `parent`=id warunku). Wiersz powstaje
        z wartością domyślną — treść ustaw potem przez `task_save`."""
        arguments = {"id": id, "what": what, "parent": parent}
        try:
            with db.connect() as con, con.transaction(), con.cursor() as cur:
                task = _load(cur, id)
                if task["review_status"] in IN_CORPUS:
                    asked = confirm.ensure(cur, confirmation, "task_add_row", arguments,
                                           f"Nowy wiersz w zadaniu #{id} z korpusu",
                                           f"{what} pod {parent}")
                    if asked is not None:
                        return asked
                if what == "criterion":
                    new_id = db.add_criterion(cur, id)
                elif what == "condition" and parent:
                    new_id = db.add_condition(cur, id, parent)
                elif what == "expression" and parent:
                    new_id = db.add_expression(cur, id, parent)
                else:
                    raise ValueError("`what` to criterion, condition albo expression; "
                                     "condition i expression wymagają `parent`")
                audit.record(cur, "task_add_row", arguments, {"id": new_id},
                             confirmation_id=confirmation)
        except (db.ValidationError, psycopg.IntegrityError, psycopg.DataError) as exc:
            raise _write_error(exc) from exc
        return {"task_id": id, "created": {what: new_id}, "url": _task_url(id),
                "field_prefix": f"{what}.{new_id}."}

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                          idempotentHint=False, openWorldHint=False),
              meta=CONFIRMED)
    def task_decide(id: int, action: str, reasons: list[str] | None = None,
                    confirmation: int | None = None) -> dict:
        """Rozstrzygnij zadanie: `approve` (do korpusu; `corrected`, gdy były poprawki),
        `reject` (poza korpus), `reopen` (z powrotem do `pending`). ZAWSZE wymaga
        zgody człowieka — agent jest pomocnikiem korektora, nie trzecim `verify`.
        `reasons` trafiają do dziennika `correction_event` jako uwagi."""
        if action not in ACTIONS:
            raise ValueError(f"nieznane rozstrzygnięcie {action!r}; znane: {', '.join(ACTIONS)}")
        arguments = {"id": id, "action": action, "reasons": reasons or []}
        model = context.model.get()
        try:
            with db.connect() as con, con.transaction(), con.cursor() as cur:
                task = _load(cur, id)
                asked = confirm.ensure(
                    cur, confirmation, "task_decide", arguments,
                    f"Rozstrzygnięcie zadania #{id} ({task['number']}, {task['year']}): {action}",
                    f"stan: {task['review_status']} → {action}\n"
                    + ("\n".join(f"- {r}" for r in (reasons or [])) or "(bez uwag)"))
                if asked is not None:
                    return asked
                changes = {"edited": {}, "deleted": {}, "described": {},
                           **({"notes": reasons} if reasons else {})}
                status = db.decide(cur, id, action, _now(), changes, actor="agent", model=model)
                audit.record(cur, "task_decide", arguments, {"status": status},
                             confirmation_id=confirmation)
        except (db.ValidationError, psycopg.IntegrityError, psycopg.DataError) as exc:
            raise _write_error(exc) from exc
        return {"task_id": id, "review_status": status, "reviewed_by": "agent",
                "review_model": model, "url": _task_url(id)}

    @mcp.tool(annotations=WRITES, meta=CONFIRMED)
    def asset_frame(asset_id: int, box: dict[str, float], page: int | None = None,
                    confirmation: int | None = None) -> dict:
        """Ramka wycinka zasobu graficznego w punktach PDF: `box` = {x0, top, x1, bottom},
        opcjonalnie `page` zeszytu. Tnie PNG do bloba tą samą funkcją co „Wytnij"
        w formularzu. Wymaga zeszytu zadań w mirrorze."""
        missing = [k for k in assets.BOX_FIELDS if k not in box]
        if missing:
            raise ValueError(f"w `box` brakuje: {', '.join(missing)}")
        fields = {f"asset.{asset_id}.{k}": str(box[k]) for k in assets.BOX_FIELDS}
        if page is not None:
            fields[f"asset.{asset_id}.page"] = str(page)
        arguments = {"asset_id": asset_id, "box": box, "page": page}
        with db.connect() as con:
            with con.cursor() as cur:
                task_id = _task_of_asset(cur, asset_id)
            return save_fields(con, task_id, fields, "asset_frame", arguments, confirmation,
                               f"Ramka zasobu #{asset_id} w zadaniu z korpusu")

    @mcp.tool(annotations=WRITES, meta=CONFIRMED)
    def asset_describe(asset_id: int, description: str, approve: bool = False,
                       confirmation: int | None = None) -> dict:
        """Opis rysunku (alt-text). Tekst inny niż w bazie daje status `corrected`
        (albo `manual`, gdy opisu nie było); `approve=True` z tym samym tekstem
        zatwierdza opis modelu (`auto` → `approved`) — to jest pomiar S7."""
        fields = {f"asset.{asset_id}.description": description}
        if approve:
            fields[f"asset.{asset_id}.approve_description"] = "1"
        arguments = {"asset_id": asset_id, "description": description, "approve": approve}
        with db.connect() as con:
            with con.cursor() as cur:
                task_id = _task_of_asset(cur, asset_id)
            return save_fields(con, task_id, fields, "asset_describe", arguments, confirmation,
                               f"Opis zasobu #{asset_id} w zadaniu z korpusu")

    @mcp.tool(annotations=READ_ONLY)
    def task_page_image(id: int, page: int | None = None) -> list:
        """Obraz strony KLUCZA z kryteriami zadania (domyślnie strona zadania) — do
        obejrzenia przez model wielomodalny. Zwraca PNG i numer strony."""
        with db.connect() as con, con.cursor() as cur:
            source = db.page_source(cur, id)
        if source is None:
            raise ValueError(f"nie ma zadania {id}")
        wanted = page or source["page"]
        if not wanted:
            raise ValueError("zadanie nie ma zapisanej strony klucza — przeładuj klucz")
        try:
            path = pages.render(source["path"], wanted)
        except pages.PageUnavailable as e:
            raise ValueError(str(e)) from e
        return [Image(path=str(path)),
                {"page": wanted, "document_pages": source["pages"],
                 "url": urls.build({"view": "task", "id": id, "page": wanted})}]
