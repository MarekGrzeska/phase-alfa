"""Przycinanie wyników narzędzi — kontekst modelu nie jest miejscem na 1436 wierszy.

Każde przycięcie jest JAWNE: wynik dostaje `truncated: true` i podpowiedź, jak
zawęzić. Obcięta prawda bez tej flagi wygląda jak cała, a to gorsze niż błąd.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

MAX_ROWS = 200
MAX_TEXT = 8_000
MAX_CELL = 400
NARROW_HINT = "Zawęź zapytanie (WHERE, LIMIT) albo popros o konkretne kolumny."


def jsonable(value: Any) -> Any:
    """Wartość z psycopg → coś, co przejdzie przez JSON bez niespodzianek."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, bytes):
        return f"<{len(value)} bajtów>"
    return str(value)


def clip_text(text: str, limit: int = MAX_TEXT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "…", True


def clip_cell(value: Any) -> Any:
    """Długi tekst w komórce ucięty, reszta bez zmian — tabela ma zostać czytelna."""
    value = jsonable(value)
    if isinstance(value, str) and len(value) > MAX_CELL:
        return value[:MAX_CELL] + "…"
    if isinstance(value, (dict, list)):
        dumped = json.dumps(value, ensure_ascii=False)
        if len(dumped) > MAX_CELL:
            return dumped[:MAX_CELL] + "…"
    return value


def clip_rows(rows: list, limit: int = MAX_ROWS) -> tuple[list, bool]:
    if len(rows) <= limit:
        return rows, False
    return rows[:limit], True


def row_dicts(rows: list[dict], limit: int = MAX_ROWS) -> dict:
    """Wiersze słownikowe → `{"rows", "row_count", "truncated"}` z przyciętymi komórkami."""
    shown, truncated = clip_rows(rows, limit)
    out = {"rows": [{k: clip_cell(v) for k, v in row.items()} for row in shown],
           "row_count": len(rows), "truncated": truncated}
    if truncated:
        out["hint"] = f"Pokazano {limit} z {len(rows)} wierszy. {NARROW_HINT}"
    return out
