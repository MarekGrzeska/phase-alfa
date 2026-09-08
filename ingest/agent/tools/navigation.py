"""Nawigacja: agent nie przełącza widoku sam — oddaje panelowi polecenie.

Narzędzie zwraca strukturę z kluczem `ui`; pętla agenta (M4) zamienia ją na
zdarzenie SSE, a panel wykonuje `window.location.assign` PO zakończeniu
odpowiedzi. Klient z terminala dostaje po prostu adres do wklejenia.
"""

from __future__ import annotations

import re

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from agent import urls

# Nazwy pól formularza korekty są stabilne (rozstrzyga o nich `db.save`):
# `task.number`, `criterion.12.points`, `asset.9.x0`, `delete.answer.3`.
FIELD_NAME = re.compile(r"^(task\.[a-z_]+|[a-z_]+\.\d+\.[a-z0-9_]+|delete\.[a-z_]+\.\d+)$")

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def ui_navigate(target: dict) -> dict:
        """Zaprowadź korektora na stronę ekranu korekty albo inspektora.

        `target` to struktura z polem `view` i parametrami widoku:
        overview (scope, status) · next (scope) · task (id, page, scope) · inspect ·
        inspect_list (table, filters, sort, direction, page, all_columns) ·
        inspect_record (table, id, pdf_page) · health (key) ·
        document_pdf (document_id, page) · document_page (document_id, page).
        `scope` = {year, code, variant}; `filters` = {"kolumna": wartość,
        "kolumna__op": wartość}, operatory: eq ne contains gt gte lt lte null notnull.
        Zwraca adres; panel przechodzi na niego po zakończeniu odpowiedzi.
        """
        url = urls.build(target)
        return {"ui": {"action": "navigate", "url": url}, "url": url, "target": target}

    @mcp.tool(annotations=READ_ONLY)
    def ui_focus(field: str) -> dict:
        """Podświetl i przewiń do pola formularza korekty na OTWARTEJ stronie zadania.

        `field` to nazwa pola w składni formularza: `task.number`, `task.max_points`,
        `task.kind`, `version.<id>.content`, `answer.<id>.answer`,
        `criterion.<id>.points|label|description`, `condition.<id>.description`,
        `expression.<id>.expression`, `asset.<id>.page|x0|top|x1|bottom|description`.
        Działa tylko, gdy korektor patrzy na formularz tego zadania — inaczej najpierw
        `ui_navigate` do widoku `task`.
        """
        if not FIELD_NAME.match(field):
            raise ValueError(f"`{field}` nie wygląda na nazwę pola formularza korekty")
        return {"ui": {"action": "focus", "name": field}, "field": field}

    @mcp.tool(annotations=READ_ONLY)
    def ui_open_pdf(document_id: int, page: int | None = None) -> dict:
        """Otwórz PDF z mirrora w nowej karcie, opcjonalnie na wskazanej stronie."""
        target = {"view": "document_pdf", "document_id": document_id}
        if page is not None:
            target["page"] = page
        url = urls.build(target)
        return {"ui": {"action": "open", "url": url}, "url": url}

    @mcp.tool(annotations=READ_ONLY)
    def ui_views() -> dict:
        """Spis widoków ekranu korekty i inspektora z parametrami — do `ui_navigate`."""
        return {"views": dict(urls.VIEWS), "scope_keys": list(urls.SCOPE_KEYS)}
