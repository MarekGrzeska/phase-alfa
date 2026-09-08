"""JSON i strumień agenta dla panelu: konfiguracja, sesje, wiadomości (SSE), zgody.

Ten sam wartownik `sec-fetch-site`, co przy zapisie zadania: rozmowa i zgoda
mają pochodzić z ekranu korekty, a nie z cudzej strony w tej samej przeglądarce.
Brak nagłówka (curl, klient bez przeglądarki) przepuszczamy — bramka ma odciąć
STRONĘ, nie konsolę.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent import confirm, conversation, limits, runtime
from correction import db

router = APIRouter(prefix="/api/agent")


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("sec-fetch-site", "same-origin")
    if origin != "same-origin":
        raise HTTPException(403, f"żądanie spoza ekranu korekty (sec-fetch-site: {origin})")


def sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def stream(events: AsyncIterator[dict]) -> StreamingResponse:
    async def body():
        async for event in events:
            yield sse(event)

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ konfiguracja

@router.get("/config")
def config() -> dict:
    return runtime.config()


# ------------------------------------------------------------------ sesje

class NewSession(BaseModel):
    model: str | None = None
    screen: dict | None = None


class NewMessage(BaseModel):
    text: str
    screen: dict | None = None


class Decision(BaseModel):
    decision: str


def _session(cur, session_id: int) -> dict:
    session = conversation.get_session(cur, session_id)
    if session is None:
        raise HTTPException(404, f"nie ma rozmowy #{session_id}")
    return session


@router.get("/sessions")
def sessions(limit: int = 20) -> dict:
    with db.connect() as con, con.cursor() as cur:
        return {"sessions": conversation.list_sessions(cur, max(1, min(limit, 100)))}


@router.post("/sessions")
def create_session(request: Request, payload: NewSession) -> dict:
    require_same_origin(request)
    model = payload.model or runtime.default_model()
    if model not in runtime.AGENT_MODELS:
        raise HTTPException(400, f"model {model!r} spoza listy; do wyboru: "
                            f"{', '.join(runtime.AGENT_MODELS)}")
    with db.connect() as con, con.transaction(), con.cursor() as cur:
        return conversation.create_session(cur, model, payload.screen)


@router.get("/sessions/{session_id}")
def session(session_id: int) -> dict:
    with db.connect() as con, con.cursor() as cur:
        found = _session(cur, session_id)
        return {
            "session": found,
            "messages": conversation.messages(cur, session_id),
            "tool_calls": conversation.tool_calls(cur, session_id),
            "usage": conversation.usage(cur, session_id),
            "pending": conversation.pending_confirmations(cur, session_id),
            "running": session_id in runtime.RUNNING,
        }


@router.post("/sessions/{session_id}/messages")
def message(request: Request, session_id: int, payload: NewMessage) -> StreamingResponse:
    require_same_origin(request)
    if not payload.text.strip():
        raise HTTPException(400, "pusta wiadomość")
    with db.connect() as con, con.cursor() as cur:
        found = _session(cur, session_id)
    if session_id in runtime.RUNNING:
        raise HTTPException(409, "w tej rozmowie właśnie biegnie odpowiedź")
    try:
        runtime.check_model(found["model"])
    except runtime.AgentError as e:
        raise HTTPException(503, str(e)) from e
    return stream(runtime.run_turn(found, payload.text, payload.screen))


@router.post("/sessions/{session_id}/confirmations/{confirmation_id}")
def resume(request: Request, session_id: int, confirmation_id: int,
           payload: Decision) -> StreamingResponse:
    """Decyzja z panelu: zapis w `agent_confirmation` i wznowienie przerwanej tury."""
    require_same_origin(request)
    with db.connect() as con, con.cursor() as cur:
        found = _session(cur, session_id)
    if session_id in runtime.RUNNING:
        raise HTTPException(409, "w tej rozmowie właśnie biegnie odpowiedź")
    try:
        with db.connect() as con, con.transaction(), con.cursor() as cur:
            confirm.decide(cur, confirmation_id, payload.decision)
    except ValueError as e:
        raise HTTPException(404 if "nie istnieje" in str(e) else 400, str(e)) from e
    return stream(runtime.resume_turn(found, confirmation_id, payload.decision))


# ------------------------------------------------------------------ zgody spoza panelu

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
