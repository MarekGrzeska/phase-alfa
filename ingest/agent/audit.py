"""Dziennik wywołań narzędzi — kto, co i z jakim skutkiem zmienił w bazie."""

from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb

from agent import confirm, context

SUMMARY_LENGTH = 400


def record(cur, tool: str, arguments: dict[str, Any], result: Any, *,
           is_error: bool = False, confirmation_id: int | None = None,
           duration_ms: int | None = None) -> int:
    summary = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False,
                                                                 default=str)
    cur.execute(
        """INSERT INTO agent_tool_call
               (session_id, message_id, tool, arguments, result_summary, is_error,
                confirmation_id, duration_ms)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (context.session_id.get(), context.message_id.get(), tool,
         Jsonb(confirm.canonical(arguments)), summary[:SUMMARY_LENGTH], is_error,
         confirmation_id, duration_ms),
    )
    return cur.fetchone()["id"]
