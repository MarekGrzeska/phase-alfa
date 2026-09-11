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

# Surowy plik (PNG strony, PDF) NIE jest widokiem: przejście na niego wyprowadza
# korektora z aplikacji do gołego obrazka, bez panelu i bez przycisku „wstecz"
# w sensie narzędzia. Stronę dokumentu pokazuje wiersz inspektora, który ma
# podgląd z przewijaniem — i to on jest właściwym celem nawigacji.
FILE_VIEWS = frozenset({"document_pdf", "document_page"})


def in_app(target: dict) -> tuple[dict, str | None]:
    """Cel wskazujący na plik → najbliższy widok W APLIKACJI, plus powód zamiany."""
    if target.get("view") not in FILE_VIEWS:
        return target, None
    document_id = target.get("document_id")
    if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id < 1:
        raise urls.BadTarget("`document_id` musi być dodatnią liczbą całkowitą")
    inside: dict = {"view": "inspect_record", "table": "document", "id": document_id}
    if target.get("page") is not None:
        inside["pdf_page"] = target["page"]
    return inside, (
        "Cel wskazywał surowy plik, który wyprowadza korektora z ekranu. Zamieniono na "
        "wiersz dokumentu w inspektorze, gdzie ta sama strona jest w podglądzie, "
        "z przewijaniem i resztą narzędzia dookoła. Sam plik w nowej karcie: `ui_open_pdf`."
    )


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    def ui_navigate(target: dict) -> dict:
        """Zaprowadź korektora na stronę ekranu korekty albo inspektora.

        `target` to struktura z polem `view` i parametrami widoku:
        overview (scope, status) · next (scope) · task (id, page, scope) · inspect ·
        inspect_list (table, filters, sort, direction, page, all_columns) ·
        inspect_record (table, id, pdf_page) · health (key).
        `scope` = {year, code, variant}; `filters` = {"kolumna": wartość,
        "kolumna__op": wartość}, operatory: eq ne contains gt gte lt lte null notnull.

        Żeby pokazać STRONĘ dokumentu, zostań w aplikacji: `task` z `page` (strona
        klucza przy formularzu zadania) albo `inspect_record` z `pdf_page` (podgląd
        w wierszu, `table: "document"` dla samego pliku). Cele `document_pdf`
        i `document_page` to surowe pliki — zostaną zamienione na widok w aplikacji;
        do otwarcia pliku w nowej karcie służy `ui_open_pdf`.

        Zwraca adres; panel przechodzi na niego po zakończeniu odpowiedzi.
        """
        wanted, note = in_app(target)
        url = urls.build(wanted)
        out = {"ui": {"action": "navigate", "url": url}, "url": url, "target": wanted}
        if note is not None:
            out["note"] = note
        return out

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
        return {"views": dict(urls.VIEWS), "scope_keys": list(urls.SCOPE_KEYS),
                "not_for_navigate": sorted(FILE_VIEWS),
                "page_hint": "Stronę dokumentu pokazuj przez `task` z `page` albo "
                             "`inspect_record` z `pdf_page`; pliki otwiera `ui_open_pdf`."}
