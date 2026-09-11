"""Potwierdzenie człowieka jako cecha narzędzia, nie logika panelu.

Narzędzie zmieniające dane albo kosztujące woła się dwa razy: bez `confirmation`
dostaje wpis w `agent_confirmation` i zwraca go modelowi (to nie jest błąd —
model ma poczekać); z `confirmation=<id>` wykonuje się tylko wtedy, gdy człowiek
kliknął „Wykonaj" w panelu i argumenty są DOKŁADNIE te same. Klient z terminala
przechodzi tę samą bramkę — nie ma tylnego wejścia.
"""

from __future__ import annotations

import json
from typing import Any

from psycopg.types.json import Jsonb

from agent import context

HOW = ("Czekaj na decyzję człowieka w panelu ekranu korekty (albo poproś go o nią), "
       "potem wywołaj to samo narzędzie z tymi samymi argumentami i `confirmation=<id>`.")


def canonical(arguments: dict[str, Any]) -> dict[str, Any]:
    """Argumenty bez `confirmation`, w porządku — to one są przedmiotem zgody."""
    return json.loads(json.dumps({k: v for k, v in arguments.items() if k != "confirmation"},
                                 sort_keys=True, ensure_ascii=False, default=str))


def request(cur, tool: str, arguments: dict[str, Any], title: str, preview: str | None,
            cost_usd: float | None = None) -> dict:
    """Nowa prośba o zgodę — zwraca to, co model ma pokazać i na co czekać."""
    cur.execute(
        """INSERT INTO agent_confirmation (session_id, tool, arguments, title, preview, cost_usd)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING id, created_at""",
        (context.session_id.get(), tool, Jsonb(canonical(arguments)), title, preview,
         cost_usd),
    )
    row = cur.fetchone()
    return {"confirm": {"id": row["id"], "tool": tool, "title": title, "preview": preview,
                        "cost_usd": cost_usd, "status": "pending", "how": HOW}}


def consume(cur, confirmation_id: int, tool: str, arguments: dict[str, Any]) -> dict:
    """Zgoda → jednorazowe zużycie. Każdy inny stan to błąd z powodem po polsku."""
    cur.execute("SELECT * FROM agent_confirmation WHERE id = %s FOR UPDATE",
                (confirmation_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"nie ma potwierdzenia #{confirmation_id}")
    if row["tool"] != tool:
        raise ValueError(f"potwierdzenie #{confirmation_id} dotyczy narzędzia "
                         f"`{row['tool']}`, nie `{tool}`")
    if row["arguments"] != canonical(arguments):
        raise ValueError(f"potwierdzenie #{confirmation_id} dotyczy innych argumentów — "
                         "poproś o nową zgodę na to, co chcesz wykonać")
    if row["used_at"] is not None:
        raise ValueError(f"potwierdzenie #{confirmation_id} zostało już wykorzystane")
    if row["decision"] is None:
        raise ValueError(f"potwierdzenie #{confirmation_id} czeka na decyzję człowieka. {HOW}")
    if row["decision"] == "reject":
        raise ValueError(f"człowiek odrzucił potwierdzenie #{confirmation_id} — "
                         "nie wykonuj tej operacji; zapytaj, co zrobić inaczej")
    cur.execute("UPDATE agent_confirmation SET used_at = now() WHERE id = %s",
                (confirmation_id,))
    return row


def ensure(cur, confirmation: int | None, tool: str, arguments: dict[str, Any],
           title: str, preview: str | None, cost_usd: float | None = None) -> dict | None:
    """Jedno wejście dla narzędzi: prośba o zgodę albo `None`, gdy wolno działać."""
    if confirmation is None:
        return request(cur, tool, arguments, title, preview, cost_usd)
    consume(cur, int(confirmation), tool, arguments)
    return None


def pending(cur, limit: int = 50) -> list[dict]:
    cur.execute(
        """SELECT id, session_id, tool, arguments, title, preview, cost_usd, created_at
           FROM agent_confirmation WHERE decision IS NULL
           ORDER BY created_at LIMIT %s""",
        (limit,),
    )
    return cur.fetchall()


def decide(cur, confirmation_id: int, decision: str) -> dict:
    if decision not in ("accept", "reject"):
        raise ValueError(f"nieznana decyzja: {decision!r}")
    cur.execute(
        """UPDATE agent_confirmation SET decision = %s, decided_at = now()
           WHERE id = %s AND decision IS NULL
           RETURNING id, tool, title, decision""",
        (decision, confirmation_id),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"potwierdzenie #{confirmation_id} nie istnieje albo już rozstrzygnięte")
    return row
