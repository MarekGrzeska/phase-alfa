"""JSON dla frontu ekranu korekty — dane bez HTML-a wokół nich.

Trasy `/api/*` powstają w miarę, jak kolejne ekrany przechodzą na Reacta.
Kształt odpowiedzi jest ten sam, co kontekst szablonu, który zastąpiła:
migracja ma zmienić SPOSÓB rysowania widoku, a nie to, co widok pokazuje.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
