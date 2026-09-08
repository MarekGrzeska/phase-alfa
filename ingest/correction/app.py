"""Ekran korekty — FastAPI, widoki w trakcie migracji z Jinja2 na Reacta.

Narzędzie na trzy tygodnie pracy jednej osoby na localhoście. Reguła stopu
z Planu Implementacji obowiązuje tu podwójnie: widok jest zrobiony, gdy
odpowiada na pytanie, dla którego powstał. Każda godzina w stylach tego ekranu
jest godziną zdjętą z korekty, a to korekta jest ścieżką krytyczną A2.

Front stoi w `ui/` (React + Vite, build do `static/`), a ten moduł oddaje mu
skorupę z nazwą widoku plus dane przez `/api/*`. Jinja została wyłącznie do
`app.html` — jednej strony na wszystkie ekrany.

Trasy plików (strona klucza, wycinek, PDF) zostają tutaj: to strumienie
bajtów z mirrora i bloba, a nie widok.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from agent.server import session_manager as mcp_session_manager
from correction import api, assets, db, inspect_api, inspector, pages
from pdf import crop as crop_pdf


class McpEndpoint:
    """ASGI pod `/mcp`. Menedżer sesji żyje tyle, co aplikacja — zakłada go cykl życia.

    Gotowa aplikacja Starlette z SDK poszła do kosza: montowana pod `/mcp`
    odpowiadała przekierowaniem 307 na `/mcp/`, za którym klient MCP nie pójdzie.
    """

    def __init__(self) -> None:
        self.manager: StreamableHTTPSessionManager | None = None

    async def __call__(self, scope, receive, send) -> None:
        if self.manager is None:
            raise RuntimeError("serwer MCP nie wystartował — brak cyklu życia aplikacji")
        await self.manager.handle_request(scope, receive, send)


MCP_ENDPOINT = McpEndpoint()


@asynccontextmanager
async def lifespan(_: FastAPI):
    manager = mcp_session_manager()
    async with manager.run():
        MCP_ENDPOINT.manager = manager
        try:
            yield
        finally:
            MCP_ENDPOINT.manager = None


app = FastAPI(title="Klucz — ekran korekty", docs_url=None, redoc_url=None,
              lifespan=lifespan)

# Te same narzędzia, które ma agent w panelu, dla klienta z zewnątrz (Claude Code):
#   claude mcp add --transport http klucz http://127.0.0.1:8600/mcp
app.add_route("/mcp", MCP_ENDPOINT, methods=["GET", "POST", "DELETE"])

# Front z `ui/` (React) po zbudowaniu — `task correction:ui`. Katalog powstaje
# dopiero z buildu, więc `check_dir=False`: brak paczki ma zabrać panel agenta,
# a nie wywalić cały ekran korekty przy starcie.
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC), check_dir=False), name="static")

app.include_router(api.router)
app.include_router(inspect_api.router)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["STATUS_LABELS"] = db.STATUS_LABELS
templates.env.globals["TASK_KINDS"] = db.TASK_KINDS


# ------------------------------------------------------------------ pomocnicze

def _scope_query(scope: dict) -> str:
    return urlencode({k: v for k, v in scope.items() if v is not None})


# ----------------------------------------------------------------------- trasy

@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Przegląd korekty. Widok rysuje React, dane bierze z `/api/overview`.

    Filtry NIE są tu czytane: ten sam adres z parametrami czyta front i podaje
    je zapytaniu. Serwer oddaje tylko skorupę, więc nie ma dwóch miejsc,
    w których „pusty rocznik" znaczy coś innego.
    """
    return templates.TemplateResponse(
        request, "app.html", {"title": "Postęp korekty", "view": "overview"})


@app.get("/next")
def next_task(year: str = "", code: str = "", variant: str = "") -> RedirectResponse:
    """Wejście do pracy: pierwsze nierozstrzygnięte zadanie w kolejności arkuszy."""
    scope = db.parse_scope(year, code, variant)
    with db.connect() as con, con.cursor() as cur:
        task_id = db.next_pending(cur, **scope)
    query = _scope_query(scope)
    if task_id is None:
        return RedirectResponse(f"/?{query}" if query else "/", status_code=303)
    return RedirectResponse(f"/task/{task_id}" + (f"?{query}" if query else ""),
                            status_code=303)


@app.get("/task/{task_id}", response_class=HTMLResponse)
def task_form(request: Request, task_id: int) -> HTMLResponse:
    """Formularz korekty. Widok rysuje React, dane bierze z `/api/task/{id}`.

    Istnienie zadania sprawdzamy TUTAJ: adres z ręki albo ze starej zakładki ma
    dać 404 od razu, a nie pustą skorupę, która dopiero po chwili powie, że nie
    ma czego korygować.
    """
    with db.connect() as con, con.cursor() as cur:
        if db.load_task(cur, task_id) is None:
            raise HTTPException(404, f"nie ma zadania {task_id}")
    return templates.TemplateResponse(
        request, "app.html", {"title": f"Zadanie {task_id}", "view": "task"})


@app.get("/task/{task_id}/page.png")
def task_page(task_id: int, n: int | None = None) -> FileResponse:
    with db.connect() as con, con.cursor() as cur:
        source = db.page_source(cur, task_id)
    if source is None:
        raise HTTPException(404, f"nie ma zadania {task_id}")
    page = n or source["page"]
    if not page:
        raise HTTPException(
            404,
            "to zadanie nie ma zapisanej strony w kluczu — klucz wczytano razem "
            "z arkuszami przed migracją 0004. Przeładuj go: task ingest",
        )
    try:
        return FileResponse(pages.render(source["path"], page), media_type="image/png")
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e


@app.get("/asset/{asset_id}.png")
def asset_crop(asset_id: int) -> FileResponse:
    """Wycinek z bloba — to, co zobaczy przeglądarka korpusu (W2)."""
    with db.connect() as con, con.cursor() as cur:
        asset = assets.source(cur, asset_id)
    if asset is None:
        raise HTTPException(404, f"nie ma zasobu {asset_id}")
    try:
        path = crop_pdf.target_path(asset["path"])
    except crop_pdf.CropError as e:
        raise HTTPException(404, str(e)) from e
    if not path.exists():
        raise HTTPException(404, "ten zasób nie ma jeszcze wycinka — dociągnij ramkę")
    return FileResponse(path, media_type="image/png")


@app.get("/asset/{asset_id}/page.png")
def asset_page(asset_id: int, n: int | None = None, grid: str = "1") -> FileResponse:
    """Strona ZESZYTU ZADAŃ, z której tnie się wycinek — domyślnie z siatką."""
    with db.connect() as con, con.cursor() as cur:
        asset = assets.source(cur, asset_id)
    if asset is None:
        raise HTTPException(404, f"nie ma zasobu {asset_id}")
    if asset["paper_path"] is None:
        raise HTTPException(
            404,
            "ta wersja zadania nie ma w bazie zeszytu zadań — przeładuj klucz "
            "poleceniem `task ingest -- --with-papers`",
        )
    try:
        return FileResponse(
            pages.render(asset["paper_path"], n or asset["page"], grid=grid == "1"),
            media_type="image/png")
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e


# ------------------------------------------------------------------ inspektor
# Tylko odczyt. Nazwa tabeli z adresu przechodzi przez allowlistę ze schematu,
# a nieznana kończy się 404 — nie ma drogi z URL-a do tekstu SQL-a.

@app.get("/inspect", response_class=HTMLResponse)
def inspect_index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "app.html", {"title": "Inspektor danych", "view": "inspect"})


@app.get("/inspect/health/{key}", response_class=HTMLResponse)
def inspect_health(request: Request, key: str) -> HTMLResponse:
    if key not in inspector.CHECK_BY_KEY:
        raise HTTPException(404, f"nie ma takiej kontroli: {key}")
    return templates.TemplateResponse(
        request, "app.html", {"title": "Zdrowie danych", "view": "inspectHealth"})


@app.get("/inspect/document/{document_id}.pdf")
def inspect_pdf(document_id: int) -> FileResponse:
    with db.connect() as con, con.cursor() as cur:
        cur.execute("SELECT path FROM document WHERE id = %s", (document_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, f"nie ma dokumentu {document_id}")
    try:
        path = pages.source_pdf(row["path"])
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e
    if not path.exists():
        raise HTTPException(404, f"pliku nie ma w mirrorze: {row['path']}")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/inspect/document/{document_id}/page/{n}.png")
def inspect_page(document_id: int, n: int) -> FileResponse:
    with db.connect() as con, con.cursor() as cur:
        cur.execute("SELECT path FROM document WHERE id = %s", (document_id,))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(404, f"nie ma dokumentu {document_id}")
    try:
        return FileResponse(pages.render(row["path"], n), media_type="image/png")
    except pages.PageUnavailable as e:
        raise HTTPException(404, str(e)) from e


@app.get("/inspect/{table}", response_class=HTMLResponse)
def inspect_list(request: Request, table: str) -> HTMLResponse:
    """Lista wierszy tabeli. Widok rysuje React, dane bierze z `/api/inspect/{table}`.

    Nazwę tabeli sprawdzamy tutaj, żeby literówka w adresie dała 404 od razu —
    tak samo, jak dawała, gdy stronę składał serwer.
    """
    with db.connect() as con, con.cursor() as cur:
        if table not in inspector.schema(cur):
            raise HTTPException(404, f"nie ma takiej tabeli: {table}")
    return templates.TemplateResponse(
        request, "app.html", {"title": f"{table} · Inspektor", "view": "inspectList"})


@app.get("/inspect/{table}/{row_id}", response_class=HTMLResponse)
def inspect_record(request: Request, table: str, row_id: int) -> HTMLResponse:
    with db.connect() as con, con.cursor() as cur:
        if table not in inspector.schema(cur):
            raise HTTPException(404, f"nie ma takiej tabeli: {table}")
    return templates.TemplateResponse(
        request, "app.html", {"title": f"{table} #{row_id} · Inspektor",
                              "view": "inspectRecord"})
