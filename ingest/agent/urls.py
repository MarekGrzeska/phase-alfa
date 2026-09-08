"""Adresy ekranu korekty i inspektora — jedno miejsce, z którego agent je bierze.

Routing narzędzia jest po stronie serwera (rozstrzygnięcie z 8.09.2026), więc
„zaprowadź do zadania" to gotowy adres, a nie stan komponentu. Cel przychodzi
strukturą (`{"view": "task", "id": 42}`), a nie stringiem: model nie ma
sklejać adresów z pamięci, bo pomyli `_sort` z `sort` i nikt tego nie zauważy.

Test pilnuje, że każdy widok tutaj odpowiada trasie w `correction/app.py`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from correction import inspector

SCOPE_KEYS = ("year", "code", "variant")

VIEWS = {
    "overview": "przegląd korekty: liczby, lista zadań w zakresie (`scope`, `status`)",
    "next": "pierwsze nierozstrzygnięte zadanie w zakresie (`scope`)",
    "task": "formularz korekty zadania (`id`, opcjonalnie `page` klucza, `scope`)",
    "inspect": "spis tabel inspektora ze zdrowiem danych",
    "inspect_list": "lista wierszy tabeli (`table`, `filters`, `sort`, `direction`, "
                    "`page`, `all_columns`)",
    "inspect_record": "wiersz tabeli z pochodzeniem (`table`, `id`, opcjonalnie `pdf_page`)",
    "health": "lista wierszy jednej kontroli zdrowia (`key`)",
    "document_pdf": "cały PDF z mirrora (`document_id`, opcjonalnie `page`)",
    "document_page": "strona PDF jako PNG (`document_id`, `page`)",
}


class BadTarget(ValueError):
    """Cel nawigacji, z którego nie da się złożyć adresu — z powodem po polsku."""


def _scope_query(target: dict) -> list[tuple[str, str]]:
    scope = target.get("scope") or {}
    return [(k, str(scope[k])) for k in SCOPE_KEYS if scope.get(k) not in (None, "")]


def _int(target: dict, key: str) -> int:
    value = target.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BadTarget(f"`{key}` musi być dodatnią liczbą całkowitą, jest: {value!r}")
    return value


def _table(target: dict) -> str:
    table = target.get("table")
    if not isinstance(table, str) or not table.isidentifier():
        raise BadTarget(f"`table` musi być nazwą tabeli, jest: {table!r}")
    return table


def _with_query(path: str, parts: list[tuple[str, str]]) -> str:
    query = urlencode(parts)
    return f"{path}?{query}" if query else path


def build(target: dict[str, Any]) -> str:
    """Cel → adres względny ekranu korekty. Nieznany widok albo brak pola = błąd."""
    view = target.get("view")
    if view not in VIEWS:
        raise BadTarget(f"nieznany widok {view!r}; znane: {', '.join(VIEWS)}")

    if view == "overview":
        parts = _scope_query(target)
        if target.get("status"):
            parts.insert(0, ("status", str(target["status"])))
        return _with_query("/", parts)
    if view == "next":
        return _with_query("/next", _scope_query(target))
    if view == "task":
        parts = []
        if target.get("page") is not None:
            parts.append(("page", str(_int(target, "page"))))
        parts += _scope_query(target)
        return _with_query(f"/task/{_int(target, 'id')}", parts)
    if view == "inspect":
        return "/inspect"
    if view == "inspect_list":
        return _inspect_list(target)
    if view == "inspect_record":
        parts = []
        if target.get("pdf_page") is not None:
            parts.append(("_pdfpage", str(_int(target, "pdf_page"))))
        return _with_query(f"/inspect/{_table(target)}/{_int(target, 'id')}", parts)
    if view == "health":
        key = target.get("key")
        if key not in inspector.CHECK_BY_KEY:
            raise BadTarget(f"nieznana kontrola {key!r}; znane: "
                            f"{', '.join(inspector.CHECK_BY_KEY)}")
        return f"/inspect/health/{key}"
    if view == "document_pdf":
        url = f"/inspect/document/{_int(target, 'document_id')}.pdf"
        if target.get("page") is not None:
            url += f"#page={_int(target, 'page')}"
        return url
    return f"/inspect/document/{_int(target, 'document_id')}/page/{_int(target, 'page')}.png"


def _inspect_list(target: dict) -> str:
    """Filtry w składni inspektora: `kolumna` = równość, `kolumna__op` = operator.

    Sprawdzamy tu tylko SKŁADNIĘ (operator z listy); czy kolumna istnieje, wie
    dopiero baza — i to ona odpowie „filtr pominięty", tak jak człowiekowi.
    """
    parts: list[tuple[str, str]] = []
    for key, value in (target.get("filters") or {}).items():
        column, _, op = str(key).partition("__")
        if not column.isidentifier():
            raise BadTarget(f"filtr {key!r}: nazwa kolumny nie jest identyfikatorem")
        if op and op not in inspector.OPERATORS:
            raise BadTarget(f"filtr {key!r}: nieznany operator {op!r}; znane: "
                            f"{', '.join(inspector.OPERATORS)}")
        parts.append((str(key), "" if value is None else str(value)))
    if target.get("sort"):
        parts.append(("_sort", str(target["sort"])))
        parts.append(("_dir", "desc" if target.get("direction") == "desc" else "asc"))
    if target.get("all_columns"):
        parts.append(("_cols", "all"))
    if target.get("page") not in (None, 1):
        parts.append(("_page", str(_int(target, "page"))))
    return _with_query(f"/inspect/{_table(target)}", parts)
