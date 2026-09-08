"""JSON agenta dla panelu — na razie potwierdzenia; rozmowa i strumień wchodzą w M4.

Ten sam wartownik `sec-fetch-site`, co przy zapisie zadania: zgoda na zmianę
korpusu ma pochodzić z ekranu korekty, a nie z cudzej strony otwartej w tej
samej przeglądarce. Brak nagłówka (curl, klient bez przeglądarki) przepuszczamy —
bramka ma odciąć STRONĘ, nie konsolę.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from agent import confirm, limits
from correction import db

router = APIRouter(prefix="/api/agent")


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("sec-fetch-site", "same-origin")
    if origin != "same-origin":
        raise HTTPException(403, f"żądanie spoza ekranu korekty (sec-fetch-site: {origin})")


class Decision(BaseModel):
    decision: str


@router.get("/confirmations")
def confirmations() -> dict:
    """Prośby o zgodę czekające na człowieka — także te z klienta w terminalu."""
    with db.connect() as con, con.cursor() as cur:
        return {"pending": limits.jsonable(confirm.pending(cur))}


@router.post("/confirmations/{confirmation_id}")
def decide(request: Request, confirmation_id: int, payload: Decision) -> dict:
    require_same_origin(request)
    try:
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            return limits.jsonable(confirm.decide(cur, confirmation_id, payload.decision))
    except ValueError as e:
        raise HTTPException(404 if "nie istnieje" in str(e) else 400, str(e)) from e
