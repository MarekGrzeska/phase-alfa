"""Rozmowy agenta w Postgresie: sesja = jeden model, wiadomości = historia do odtworzenia.

W bazie, a nie w przeglądarce, bo nawigacja w ekranie przeładowuje stronę,
a koszt tokenów jest liczbą do raportu. Wpisy `agent_tool_call` z rozmowy
pisze pętla (`runtime`), nie narzędzia — te logują tylko wywołania z zewnątrz.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from agent import limits


def create_session(cur, model: str, screen: dict | None = None,
                   title: str | None = None) -> dict:
    cur.execute(
        """INSERT INTO agent_session (model, screen, title) VALUES (%s, %s, %s)
           RETURNING id, model, title, screen, created_at""",
        (model, Jsonb(screen) if screen else None, title),
    )
    return limits.jsonable(cur.fetchone())


def get_session(cur, session_id: int) -> dict | None:
    cur.execute("SELECT id, model, title, screen, created_at FROM agent_session WHERE id = %s",
                (session_id,))
    row = cur.fetchone()
    return limits.jsonable(row) if row else None


def list_sessions(cur, limit: int = 20) -> list[dict]:
    cur.execute(
        """SELECT s.id, s.model, s.title, s.created_at,
                  (SELECT count(*) FROM agent_message m WHERE m.session_id = s.id) AS messages,
                  (SELECT max(m.created_at) FROM agent_message m WHERE m.session_id = s.id)
                      AS last_message_at
           FROM agent_session s ORDER BY s.id DESC LIMIT %s""",
        (limit,),
    )
    return limits.jsonable(cur.fetchall())


def update_screen(cur, session_id: int, screen: dict | None) -> None:
    if screen:
        cur.execute("UPDATE agent_session SET screen = %s WHERE id = %s",
                    (Jsonb(screen), session_id))


def set_title(cur, session_id: int, title: str) -> None:
    cur.execute("UPDATE agent_session SET title = %s WHERE id = %s AND title IS NULL",
                (title[:120], session_id))


def add_message(cur, session_id: int, role: str, content: str,
                tool_calls: list[dict] | None = None,
                input_tokens: int = 0, output_tokens: int = 0) -> int:
    cur.execute(
        """INSERT INTO agent_message
               (session_id, role, content, tool_calls, input_tokens, output_tokens)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (session_id, role, content, Jsonb(tool_calls) if tool_calls else None,
         input_tokens, output_tokens),
    )
    return cur.fetchone()["id"]


def messages(cur, session_id: int) -> list[dict]:
    cur.execute(
        """SELECT id, role, content, tool_calls, input_tokens, output_tokens, created_at
           FROM agent_message WHERE session_id = %s ORDER BY id""",
        (session_id,),
    )
    return limits.jsonable(cur.fetchall())


def tool_calls(cur, session_id: int) -> list[dict]:
    cur.execute(
        """SELECT id, message_id, tool, arguments, result_summary, is_error,
                  confirmation_id, duration_ms, created_at
           FROM agent_tool_call WHERE session_id = %s ORDER BY id""",
        (session_id,),
    )
    return limits.jsonable(cur.fetchall())


def usage(cur, session_id: int) -> dict[str, Any]:
    cur.execute(
        """SELECT coalesce(sum(input_tokens), 0) AS input_tokens,
                  coalesce(sum(output_tokens), 0) AS output_tokens,
                  count(*) FILTER (WHERE role = 'agent') AS turns
           FROM agent_message WHERE session_id = %s""",
        (session_id,),
    )
    return limits.jsonable(cur.fetchone())


def pending_confirmations(cur, session_id: int) -> list[dict]:
    cur.execute(
        """SELECT id, tool, arguments, title, preview, cost_usd, created_at
           FROM agent_confirmation WHERE session_id = %s AND decision IS NULL
           ORDER BY id""",
        (session_id,),
    )
    return limits.jsonable(cur.fetchall())
