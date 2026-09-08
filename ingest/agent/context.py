"""Kto woła narzędzie: sesja panelu i jej model, albo klient z zewnątrz.

Zmienne kontekstowe, bo narzędzia MCP nie mają w sygnaturze miejsca na sesję,
a rekord w korpusie ma nieść, który model rozstrzygał. Pętla agenta (M4)
ustawia je przed otwarciem sesji in-memory; klient z terminala ich nie ma
i dostaje wartości domyślne.
"""

from __future__ import annotations

from contextvars import ContextVar

# Klient spoza panelu (Claude Code po stdio albo /mcp) — bez sesji i bez cennika.
EXTERNAL_MODEL = "mcp:external"

session_id: ContextVar[int | None] = ContextVar("agent_session_id", default=None)
model: ContextVar[str] = ContextVar("agent_model", default=EXTERNAL_MODEL)
message_id: ContextVar[int | None] = ContextVar("agent_message_id", default=None)
