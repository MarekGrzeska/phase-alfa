"""Dziennik wywołań narzędzi — kto, co i z jakim skutkiem zmienił w bazie.

Narzędzia logują tylko wywołania spoza rozmowy (klient w terminalu): w rozmowie
pisze pętla agenta, która widzi każde wywołanie, także odczyty, i zna wiersz
wiadomości. Inaczej zapis byłby w dzienniku dwa razy.
"""

from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb

from agent import confirm, context

SUMMARY_LENGTH = 400


def record(cur, tool: str, arguments: dict[str, Any], result: Any, *,
           is_error: bool = False, confirmation_id: int | None = None,
           duration_ms: int | None = None, message_id: int | None = None,
           force: bool = False) -> int | None:
    session = context.session_id.get()
    if session is not None and not force:
        return None
    summary = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False,
                                                                 default=str)
    cur.execute(
        """INSERT INTO agent_tool_call
               (session_id, message_id, tool, arguments, result_summary, is_error,
                confirmation_id, duration_ms)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (session, message_id if message_id is not None else context.message_id.get(), tool,
         Jsonb(confirm.canonical(arguments)), summary[:SUMMARY_LENGTH], is_error,
         confirmation_id, duration_ms),
    )
    return cur.fetchone()["id"]
